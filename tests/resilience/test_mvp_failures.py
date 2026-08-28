from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from ia_mcp.contracts.appointments import AppointmentStatus
from ia_mcp.scheduling.models import AppointmentScheduledEvent, SchedulingPolicy
from ia_mcp.scheduling.service import SqlAlchemyJobStore
from ia_mcp.scheduling.worker import JobWorker
from ia_mcp.workflows.adapters.sqlalchemy import SqlAlchemyWorkflowRepository
from ia_mcp.workflows.appointments.create import CreateAppointmentDefinition
from ia_mcp.workflows.engine import WorkflowEngine
from tests.fixtures.mvp import (
    ALL_TOOLS,
    DATABASE_URL,
    DUE_AT,
    PATIENT,
    TENANT_A_CTX,
    CapabilityAppointmentLookup,
    appointment_config,
    collect_and_select,
    create_appointment,
    make_capability,
    make_executor,
    make_scheduler,
    parse_starts_at,
    reset_and_seed,
    start_create,
)
from tests.unit.scheduling.fakes import (
    AdjustableClock,
    FakeChannelAdapter,
    InMemoryAuditSink,
)

pytestmark = [pytest.mark.anyio, pytest.mark.integration]


async def test_restarted_workflow_and_job_resume() -> None:
    """Workflow SQL restart is real; job resume uses test-side ReminderScheduler.upsert."""
    reset_and_seed()
    capability = make_capability()
    executor = make_executor(capability, skill=ALL_TOOLS)
    first_db = create_async_engine(DATABASE_URL)
    try:
        started = await start_create(first_db, TENANT_A_CTX)
        selected = await collect_and_select(
            first_db, TENANT_A_CTX, executor, started.workflow_id
        )
        assert selected.data.get("selected_slot") == "slot-a-1"
        workflow_id = started.workflow_id
    finally:
        await first_db.dispose()

    second_db = create_async_engine(DATABASE_URL)
    try:
        engine = WorkflowEngine(
            SqlAlchemyWorkflowRepository(second_db), CreateAppointmentDefinition()
        )
        loaded = await SqlAlchemyWorkflowRepository(second_db).get(
            TENANT_A_CTX, workflow_id
        )
        assert loaded is not None
        assert loaded.state == "collecting"
        created = await CreateAppointmentDefinition().confirm_create(
            engine,
            executor,
            TENANT_A_CTX,
            workflow_id,
            command_id="confirm-after-restart",
            run_id=uuid4(),
            config=appointment_config(TENANT_A_CTX.tenant_id),
            patient=PATIENT,
        )
        assert created.state == "completed"
        appointment_id = str(created.data["appointment_id"])
        starts_at = parse_starts_at(created.data["starts_at"])
        scheduler, store, clock, channel, policy, audit = make_scheduler(second_db)
        await scheduler.upsert(
            TENANT_A_CTX,
            AppointmentScheduledEvent(
                appointment_id=appointment_id, starts_at=starts_at
            ),
        )
    finally:
        await second_db.dispose()

    third_db = create_async_engine(DATABASE_URL)
    try:
        store = SqlAlchemyJobStore(third_db)
        clock = AdjustableClock(DUE_AT + timedelta(seconds=1))
        policy = SchedulingPolicy()
        channel = FakeChannelAdapter()
        audit = InMemoryAuditSink()
        worker = JobWorker(
            store=store,
            clock=clock,
            channel=channel,
            lookup=CapabilityAppointmentLookup(capability),
            policy=policy,
            audit=audit,
            owner="worker-restart",
        )
        claim = await worker.claim()
        assert claim is not None
        result = await worker.dispatch(claim)
        assert result.status == "dispatched"
        assert len(channel.deliveries_for(TENANT_A_CTX)) == 1
    finally:
        await third_db.dispose()


async def test_reminder_channel_failure_after_create_is_retried_and_audited() -> None:
    """Composition: upsert after create, then channel fault injection on the worker."""
    reset_and_seed()
    db = create_async_engine(DATABASE_URL)
    try:
        capability = make_capability()
        executor = make_executor(capability, skill=ALL_TOOLS)
        created = await create_appointment(db, TENANT_A_CTX, executor)
        appointment_id = str(created.data["appointment_id"])
        starts_at = parse_starts_at(created.data["starts_at"])
        policy = SchedulingPolicy(max_attempts=3)
        channel = FakeChannelAdapter(fail_forever=True)
        scheduler, store, clock, channel, policy, audit = make_scheduler(
            db, channel=channel, policy=policy
        )
        await scheduler.upsert(
            TENANT_A_CTX,
            AppointmentScheduledEvent(
                appointment_id=appointment_id, starts_at=starts_at
            ),
        )
        clock.advance(timedelta(days=5))
        worker = JobWorker(
            store=store,
            clock=clock,
            channel=channel,
            lookup=CapabilityAppointmentLookup(capability),
            policy=policy,
            audit=audit,
            owner="mvp-fail-worker",
        )
        statuses = []
        for _ in range(3):
            claim = await worker.claim()
            assert claim is not None
            statuses.append((await worker.dispatch(claim)).status)
        assert statuses == ["retry", "retry", "failed"]
        assert audit.entries[-1]["outcome"] == "failed"
        assert all(entry["tenant_id"] == TENANT_A_CTX.tenant_id for entry in audit.entries)
        assert channel.deliveries_for(TENANT_A_CTX) == ()
        got_status = await CapabilityAppointmentLookup(capability).status(
            TENANT_A_CTX, appointment_id
        )
        assert got_status == AppointmentStatus.SCHEDULED.value
    finally:
        await db.dispose()
