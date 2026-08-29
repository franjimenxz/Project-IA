from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
from alembic.config import Config
from pydantic import SecretStr
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from alembic import command
from ia_mcp.configuration.adapters.sqlalchemy import tenant_table
from ia_mcp.contracts.appointments import (
    AppointmentCreateRequest,
    AppointmentSlot,
    AppointmentStatus,
    PatientRef,
)
from ia_mcp.mcp.executor import ToolExecutor
from ia_mcp.mcp.fakes.appointments import FakeAppointmentCapability
from ia_mcp.scheduling.ingress import ConfirmationIngress
from ia_mcp.scheduling.models import AppointmentScheduledEvent, SchedulingPolicy
from ia_mcp.scheduling.service import ReminderScheduler, SqlAlchemyJobStore
from ia_mcp.scheduling.worker import JobWorker
from ia_mcp.tenancy.models import TenantContext
from ia_mcp.workflows.appointments.confirm import ConfirmAppointmentDefinition
from ia_mcp.workflows.engine import WorkflowEngine
from tests.fixtures.database import DATABASE_URL
from tests.unit.scheduling.fakes import (
    AdjustableClock,
    FakeAppointmentLookup,
    FakeChannelAdapter,
    InMemoryAuditSink,
)
from tests.unit.workflows.fakes import InMemoryWorkflowRepository

ROOT = Path(__file__).resolve().parents[2]

TENANT_A = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
TENANT_B = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
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


def _reset_schema() -> None:
    engine = create_engine(DATABASE_URL)
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))
    engine.dispose()
    alembic_cfg = Config(str(ROOT / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(ROOT / "alembic"))
    alembic_cfg.set_main_option("sqlalchemy.url", DATABASE_URL)
    command.upgrade(alembic_cfg, "head")


def _seed_tenants() -> None:
    engine = create_engine(DATABASE_URL)
    now = datetime.now(UTC)
    with engine.begin() as connection:
        connection.execute(
            tenant_table.insert(),
            [
                {
                    "id": TENANT_A,
                    "slug": "tenant-a",
                    "status": "active",
                    "active_config_version": None,
                    "created_at": now,
                    "updated_at": now,
                },
                {
                    "id": TENANT_B,
                    "slug": "tenant-b",
                    "status": "active",
                    "active_config_version": None,
                    "created_at": now,
                    "updated_at": now,
                },
            ],
        )
    engine.dispose()


@pytest.fixture
async def db() -> AsyncIterator[AsyncEngine]:
    _reset_schema()
    _seed_tenants()
    engine = create_async_engine(DATABASE_URL)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.mark.anyio
@pytest.mark.e2e
async def test_reminder_then_yes_reply_confirms_appointment(db: AsyncEngine) -> None:
    store = SqlAlchemyJobStore(db)
    clock = AdjustableClock(datetime(2026, 8, 28, 12, 0, tzinfo=BA))
    policy = SchedulingPolicy()
    channel = FakeChannelAdapter()
    lookup = FakeAppointmentLookup()
    scheduler = ReminderScheduler(store=store, clock=clock, policy=policy)
    worker = JobWorker(
        store=store,
        clock=clock,
        channel=channel,
        lookup=lookup,
        policy=policy,
        audit=InMemoryAuditSink(),
        owner="worker-1",
    )
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
    lookup.set_status(TENANT_A, appointment_id, "scheduled")
    job = await scheduler.upsert(
        TENANT_A_CTX,
        AppointmentScheduledEvent(
            appointment_id=appointment_id, starts_at=STARTS_AT
        ),
    )
    assert job.scheduled_for == DUE_AT
    assert await worker.claim() is None
    clock.advance(timedelta(days=4))
    claim = await worker.claim()
    assert claim is not None
    dispatched = await worker.dispatch(claim)
    assert dispatched.status == "dispatched"
    assert len(channel.deliveries_for(TENANT_A_CTX)) == 1

    engine = WorkflowEngine(
        InMemoryWorkflowRepository(), ConfirmAppointmentDefinition()
    )
    executor = ToolExecutor(
        server=CONFIRM_TOOLS,
        tenant=CONFIRM_TOOLS,
        skill=CONFIRM_TOOLS,
        capability=capability,
    )
    ingress = ConfirmationIngress(store=store, engine=engine, executor=executor)
    confirmed = await ingress.apply_reply(
        TENANT_A_CTX,
        appointment_id=appointment_id,
        text="yes",
        command_id="reply-yes",
    )
    assert confirmed.state == "completed"
    assert confirmed.data["status"] == AppointmentStatus.CONFIRMED
