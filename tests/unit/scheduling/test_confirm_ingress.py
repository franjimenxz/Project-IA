from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest
from pydantic import SecretStr

from ia_mcp.contracts.appointments import (
    AppointmentCreateRequest,
    AppointmentSlot,
    AppointmentStatus,
    PatientRef,
)
from ia_mcp.mcp.executor import ToolExecutor
from ia_mcp.mcp.fakes.appointments import FakeAppointmentCapability
from ia_mcp.scheduling.models import AppointmentScheduledEvent, SchedulingPolicy
from ia_mcp.scheduling.service import ReminderScheduler
from ia_mcp.scheduling.worker import JobWorker
from ia_mcp.tenancy.models import TenantContext
from ia_mcp.workflows.appointments.confirm import ConfirmAppointmentDefinition
from ia_mcp.workflows.engine import WorkflowEngine
from tests.unit.scheduling.fakes import (
    AdjustableClock,
    FakeAppointmentLookup,
    FakeChannelAdapter,
    InMemoryAuditSink,
    InMemoryJobStore,
)
from tests.unit.workflows.fakes import InMemoryWorkflowRepository

TENANT_A = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
TENANT_A_CTX = TenantContext(
    tenant_id=TENANT_A,
    tenant_slug="tenant-a",
    config_version=1,
    correlation_id=UUID("33333333-3333-3333-3333-333333333333"),
)
BA = ZoneInfo("America/Argentina/Buenos_Aires")
STARTS_AT = datetime(2026, 9, 3, 12, 0, tzinfo=BA)
DUE_AT = datetime(2026, 9, 1, 12, 0, tzinfo=BA)
CAPABILITY_CLOCK = datetime(2026, 9, 1, 12, tzinfo=UTC)
PATIENT = PatientRef(name="Ada Lovelace", email="ada@example.com")
CONFIRM_TOOLS = frozenset({"appointments.get", "appointments.confirm"})


@pytest.mark.anyio
async def test_affirmative_reply_after_reminder_continues_confirm_workflow() -> None:
    capability = FakeAppointmentCapability(
        clock=lambda: CAPABILITY_CLOCK,
        initial_slots={
            TENANT_A: (
                AppointmentSlot(
                    slot_id="slot-a-1",
                    starts_at=STARTS_AT,
                    ends_at=datetime(2026, 9, 3, 12, 30, tzinfo=BA),
                    specialty="cardiologia",
                    practitioner="Dr. Ada",
                    location="sede-centro",
                    booking_token=SecretStr("tok-a-secret"),
                ),
            )
        },
    )
    created = await capability.create(
        TENANT_A_CTX,
        AppointmentCreateRequest(slot_id="slot-a-1", patient=PATIENT),
        idempotency_key="seed-1",
    )
    assert created.ok
    assert created.value is not None
    appointment_id = created.value.appointment_id

    clock = AdjustableClock(DUE_AT)
    store = InMemoryJobStore()
    policy = SchedulingPolicy()
    scheduler = ReminderScheduler(store=store, clock=clock, policy=policy)
    channel = FakeChannelAdapter()
    lookup = FakeAppointmentLookup()
    lookup.set_status(TENANT_A, appointment_id, "scheduled")
    worker = JobWorker(
        store=store,
        clock=clock,
        channel=channel,
        lookup=lookup,
        policy=policy,
        audit=InMemoryAuditSink(),
        owner="worker-1",
    )
    await scheduler.upsert(
        TENANT_A_CTX,
        AppointmentScheduledEvent(
            appointment_id=appointment_id, starts_at=STARTS_AT
        ),
    )
    claim = await worker.claim()
    assert claim is not None
    dispatched = await worker.dispatch(claim)
    assert dispatched.status == "dispatched"
    assert len(channel.deliveries_for(TENANT_A_CTX)) == 1

    repository = InMemoryWorkflowRepository()
    definition = ConfirmAppointmentDefinition()
    engine = WorkflowEngine(repository, definition)
    executor = ToolExecutor(
        server=CONFIRM_TOOLS,
        tenant=CONFIRM_TOOLS,
        skill=CONFIRM_TOOLS,
        capability=capability,
    )
    started = await definition.start(
        engine,
        TENANT_A_CTX,
        command_id="start-1",
        appointment_id=appointment_id,
    )
    await definition.load_appointment(
        engine,
        executor,
        TENANT_A_CTX,
        started.workflow_id,
        command_id="load-1",
        run_id=uuid4(),
    )
    result = await definition.apply_reply(
        engine,
        executor,
        TENANT_A_CTX,
        started.workflow_id,
        command_id="reply-yes",
        run_id=uuid4(),
        text="yes",
    )
    assert result.state == "completed"
    assert result.data["status"] == AppointmentStatus.CONFIRMED
