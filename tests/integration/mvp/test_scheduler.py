from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from alembic import command
from ia_mcp.configuration.adapters.sqlalchemy import tenant_table
from ia_mcp.scheduling.models import AppointmentScheduledEvent, SchedulingPolicy
from ia_mcp.scheduling.service import (
    ReminderScheduler,
    SqlAlchemyJobStore,
    scheduled_job_table,
    scheduling_outbox_table,
)
from ia_mcp.scheduling.worker import JobWorker
from ia_mcp.tenancy.models import TenantContext
from tests.fixtures.database import DATABASE_URL
from tests.unit.scheduling.fakes import (
    AdjustableClock,
    FakeAppointmentLookup,
    FakeChannelAdapter,
    InMemoryAuditSink,
)

ROOT = Path(__file__).resolve().parents[3]

TENANT_A = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
TENANT_B = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
TENANT_A_CTX = TenantContext(
    tenant_id=TENANT_A,
    tenant_slug="tenant-a",
    config_version=1,
    correlation_id=UUID("33333333-3333-3333-3333-333333333333"),
)
TENANT_B_CTX = TenantContext(
    tenant_id=TENANT_B,
    tenant_slug="tenant-b",
    config_version=1,
    correlation_id=UUID("44444444-4444-4444-4444-444444444444"),
)
BA = ZoneInfo("America/Argentina/Buenos_Aires")
STARTS_AT = datetime(2026, 9, 3, 12, 0, tzinfo=BA)
DUE_AT = datetime(2026, 9, 1, 12, 0, tzinfo=BA)


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


class Harness:
    def __init__(
        self,
        db: AsyncEngine,
        store: SqlAlchemyJobStore,
        scheduler: ReminderScheduler,
        worker: JobWorker,
        clock: AdjustableClock,
        channel: FakeChannelAdapter,
        lookup: FakeAppointmentLookup,
        audit: InMemoryAuditSink,
        policy: SchedulingPolicy,
    ) -> None:
        self.db = db
        self.store = store
        self.scheduler = scheduler
        self.worker = worker
        self.clock = clock
        self.channel = channel
        self.lookup = lookup
        self.audit = audit
        self.policy = policy


@pytest.fixture
async def harness() -> AsyncIterator[Harness]:
    _reset_schema()
    _seed_tenants()
    db = create_async_engine(DATABASE_URL)
    store = SqlAlchemyJobStore(db)
    clock = AdjustableClock(DUE_AT)
    policy = SchedulingPolicy()
    channel = FakeChannelAdapter()
    lookup = FakeAppointmentLookup()
    audit = InMemoryAuditSink()
    try:
        yield Harness(
            db,
            store,
            ReminderScheduler(store=store, clock=clock, policy=policy),
            JobWorker(
                store=store,
                clock=clock,
                channel=channel,
                lookup=lookup,
                policy=policy,
                audit=audit,
                owner="worker-1",
            ),
            clock,
            channel,
            lookup,
            audit,
            policy,
        )
    finally:
        await db.dispose()


@pytest.mark.anyio
@pytest.mark.integration
async def test_sql_upsert_schedules_48h_buenos_aires(harness: Harness) -> None:
    job = await harness.scheduler.upsert(
        TENANT_A_CTX,
        AppointmentScheduledEvent(appointment_id="appt-1", starts_at=STARTS_AT),
    )
    assert job.scheduled_for == DUE_AT
    assert job.schedule_version == 1
    loaded = await harness.store.get_by_identity(
        TENANT_A_CTX, "appointment_reminder", "appt-1:pre_appointment"
    )
    assert loaded is not None
    assert loaded.id == job.id


@pytest.mark.anyio
@pytest.mark.integration
async def test_sql_policy_lead_hours_changes_schedule() -> None:
    _reset_schema()
    _seed_tenants()
    db = create_async_engine(DATABASE_URL)
    store = SqlAlchemyJobStore(db)
    clock = AdjustableClock(DUE_AT)
    scheduler = ReminderScheduler(
        store=store, clock=clock, policy=SchedulingPolicy(lead_hours=24)
    )
    try:
        job = await scheduler.upsert(
            TENANT_A_CTX,
            AppointmentScheduledEvent(
                appointment_id="appt-1", starts_at=STARTS_AT
            ),
        )
        assert job.scheduled_for == datetime(2026, 9, 2, 12, 0, tzinfo=BA)
    finally:
        await db.dispose()


@pytest.mark.anyio
@pytest.mark.integration
async def test_sql_skip_confirmed_before_send(harness: Harness) -> None:
    harness.lookup.set_status(TENANT_A, "appt-1", "confirmed")
    await harness.scheduler.upsert(
        TENANT_A_CTX,
        AppointmentScheduledEvent(appointment_id="appt-1", starts_at=STARTS_AT),
    )
    claim = await harness.worker.claim()
    assert claim is not None
    result = await harness.worker.dispatch(claim)
    assert result.status == "skipped"
    assert harness.channel.attempts == []
    async with harness.db.connect() as connection:
        outbox_count = await connection.scalar(
            select(func.count()).select_from(scheduling_outbox_table)
        )
    assert outbox_count == 0


@pytest.mark.anyio
@pytest.mark.integration
async def test_sql_replay_does_not_duplicate_outbox(harness: Harness) -> None:
    harness.lookup.set_status(TENANT_A, "appt-1", "scheduled")
    job = await harness.scheduler.upsert(
        TENANT_A_CTX,
        AppointmentScheduledEvent(appointment_id="appt-1", starts_at=STARTS_AT),
    )
    claim = await harness.worker.claim()
    assert claim is not None
    first = await harness.worker.dispatch(claim)
    second = await harness.worker.dispatch(claim)
    assert first.status == "dispatched"
    assert second.status == "dispatched"
    assert len(harness.channel.deliveries_for(TENANT_A_CTX)) == 1
    async with harness.db.connect() as connection:
        outbox_count = await connection.scalar(
            select(func.count())
            .select_from(scheduling_outbox_table)
            .where(
                scheduling_outbox_table.c.tenant_id == TENANT_A,
                scheduling_outbox_table.c.job_id == job.id,
            )
        )
    assert outbox_count == 1


@pytest.mark.anyio
@pytest.mark.integration
async def test_sql_cancel_prevents_claim(harness: Harness) -> None:
    await harness.scheduler.upsert(
        TENANT_A_CTX,
        AppointmentScheduledEvent(appointment_id="appt-1", starts_at=STARTS_AT),
    )
    cancelled = await harness.scheduler.cancel(TENANT_A_CTX, "appt-1")
    assert cancelled is not None
    assert cancelled.status == "cancelled"
    assert await harness.worker.claim() is None


@pytest.mark.anyio
@pytest.mark.integration
async def test_sql_tenant_a_job_does_not_use_tenant_b(harness: Harness) -> None:
    harness.lookup.set_status(TENANT_A, "appt-shared", "scheduled")
    harness.lookup.set_status(TENANT_B, "appt-shared", "cancelled")
    job = await harness.scheduler.upsert(
        TENANT_A_CTX,
        AppointmentScheduledEvent(
            appointment_id="appt-shared", starts_at=STARTS_AT
        ),
    )
    claim = await harness.worker.claim()
    assert claim is not None
    result = await harness.worker.dispatch(claim)
    assert result.status == "dispatched"
    assert harness.channel.tenant_ids_used() == (TENANT_A,)
    assert harness.lookup.lookups == [(TENANT_A, "appt-shared")]
    assert await harness.store.get(TENANT_B_CTX, job.id) is None
    async with harness.db.connect() as connection:
        foreign = await connection.scalar(
            select(func.count())
            .select_from(scheduled_job_table)
            .where(scheduled_job_table.c.tenant_id == TENANT_B)
        )
    assert foreign == 0


@pytest.mark.integration
def test_scheduling_migration_up_and_down() -> None:
    _reset_schema()
    alembic_cfg = Config(str(ROOT / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(ROOT / "alembic"))
    alembic_cfg.set_main_option("sqlalchemy.url", DATABASE_URL)
    engine = create_engine(DATABASE_URL)
    with engine.connect() as connection:
        tables = set(
            connection.execute(
                text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
            )
            .scalars()
            .all()
        )
    engine.dispose()
    assert {"scheduled_job", "scheduling_outbox", "handoff"} <= tables
    command.downgrade(alembic_cfg, "0005_handoff")
    engine = create_engine(DATABASE_URL)
    with engine.connect() as connection:
        tables = set(
            connection.execute(
                text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
            )
            .scalars()
            .all()
        )
    engine.dispose()
    assert "scheduled_job" not in tables
    assert "scheduling_outbox" not in tables
    assert "handoff" in tables
    command.upgrade(alembic_cfg, "head")
