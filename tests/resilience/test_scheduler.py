from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from alembic import command
from ia_mcp.configuration.adapters.sqlalchemy import tenant_table
from ia_mcp.scheduling.models import AppointmentScheduledEvent, SchedulingPolicy
from ia_mcp.scheduling.service import ReminderScheduler, SqlAlchemyJobStore
from ia_mcp.scheduling.worker import JobWorker
from ia_mcp.tenancy.models import TenantContext
from tests.unit.scheduling.fakes import (
    AdjustableClock,
    FakeAppointmentLookup,
    FakeChannelAdapter,
    InMemoryAuditSink,
)

ROOT = Path(__file__).resolve().parents[2]
DATABASE_URL = "postgresql+psycopg://francojimenez@127.0.0.1:5432/ia_mcp_p02_t03"

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


@pytest.fixture
async def db() -> AsyncIterator[AsyncEngine]:
    _reset_schema()
    _seed_tenants()
    engine = create_async_engine(DATABASE_URL)
    try:
        yield engine
    finally:
        await engine.dispose()


def _stack(
    db: AsyncEngine,
    *,
    channel: FakeChannelAdapter | None = None,
    policy: SchedulingPolicy | None = None,
    owner: str = "worker-1",
    lock_ttl: timedelta = timedelta(minutes=5),
    clock: AdjustableClock | None = None,
) -> tuple[
    ReminderScheduler,
    JobWorker,
    SqlAlchemyJobStore,
    AdjustableClock,
    FakeChannelAdapter,
    FakeAppointmentLookup,
    InMemoryAuditSink,
    SchedulingPolicy,
]:
    store = SqlAlchemyJobStore(db)
    resolved_clock = clock or AdjustableClock(DUE_AT)
    resolved_policy = policy or SchedulingPolicy()
    resolved_channel = channel or FakeChannelAdapter()
    lookup = FakeAppointmentLookup()
    audit = InMemoryAuditSink()
    scheduler = ReminderScheduler(
        store=store, clock=resolved_clock, policy=resolved_policy
    )
    worker = JobWorker(
        store=store,
        clock=resolved_clock,
        channel=resolved_channel,
        lookup=lookup,
        policy=resolved_policy,
        audit=audit,
        owner=owner,
        lock_ttl=lock_ttl,
    )
    return (
        scheduler,
        worker,
        store,
        resolved_clock,
        resolved_channel,
        lookup,
        audit,
        resolved_policy,
    )


@pytest.mark.anyio
@pytest.mark.resilience
async def test_restarted_worker_resumes_claimed_job_after_clock_advance(
    db: AsyncEngine,
) -> None:
    scheduler, worker, store, clock, channel, lookup, audit, policy = _stack(
        db, lock_ttl=timedelta(minutes=1)
    )
    lookup.set_status(TENANT_A, "appt-1", "scheduled")
    await scheduler.upsert(
        TENANT_A_CTX,
        AppointmentScheduledEvent(appointment_id="appt-1", starts_at=STARTS_AT),
    )
    claim = await worker.claim()
    assert claim is not None
    assert claim.job.status == "claimed"
    clock.advance(timedelta(minutes=1))
    restarted = JobWorker(
        store=store,
        clock=clock,
        channel=channel,
        lookup=lookup,
        policy=policy,
        audit=audit,
        owner="worker-2",
        lock_ttl=timedelta(minutes=1),
    )
    resumed = await restarted.claim()
    assert resumed is not None
    assert resumed.owner == "worker-2"
    result = await restarted.dispatch(resumed)
    assert result.status == "dispatched"
    assert len(channel.deliveries_for(TENANT_A_CTX)) == 1


@pytest.mark.anyio
@pytest.mark.resilience
async def test_channel_failure_retries_then_fails_with_audit(
    db: AsyncEngine,
) -> None:
    policy = SchedulingPolicy(max_attempts=3)
    channel = FakeChannelAdapter(fail_forever=True)
    scheduler, worker, store, clock, channel, lookup, audit, policy = _stack(
        db, channel=channel, policy=policy
    )
    lookup.set_status(TENANT_A, "appt-1", "scheduled")
    job = await scheduler.upsert(
        TENANT_A_CTX,
        AppointmentScheduledEvent(appointment_id="appt-1", starts_at=STARTS_AT),
    )
    statuses: list[str] = []
    for _ in range(3):
        claim = await worker.claim()
        assert claim is not None
        result = await worker.dispatch(claim)
        statuses.append(result.status)
    assert statuses == ["retry", "retry", "failed"]
    loaded = await store.get(TENANT_A, job.id)
    assert loaded is not None
    assert loaded.status == "failed"
    assert loaded.attempts == 3
    assert loaded.last_error == "channel_unavailable"
    assert len(audit.entries) == 3
    assert audit.entries[0]["outcome"] == "retry"
    assert audit.entries[1]["outcome"] == "retry"
    assert audit.entries[-1]["outcome"] == "failed"
    assert all(entry["tenant_id"] == TENANT_A for entry in audit.entries)
    assert channel.deliveries_for(TENANT_A_CTX) == ()
    clock.advance(timedelta(minutes=5))
    assert await worker.claim() is None


@pytest.mark.anyio
@pytest.mark.resilience
async def test_reschedule_makes_previous_claim_stale(db: AsyncEngine) -> None:
    scheduler, worker, _store, _clock, channel, lookup, _audit, _policy = _stack(
        db
    )
    lookup.set_status(TENANT_A, "appt-1", "scheduled")
    first = await scheduler.upsert(
        TENANT_A_CTX,
        AppointmentScheduledEvent(appointment_id="appt-1", starts_at=STARTS_AT),
    )
    claim = await worker.claim()
    assert claim is not None
    assert claim.schedule_version == 1
    rescheduled = await scheduler.upsert(
        TENANT_A_CTX,
        AppointmentScheduledEvent(
            appointment_id="appt-1",
            starts_at=datetime(2026, 9, 4, 12, 0, tzinfo=BA),
        ),
    )
    assert rescheduled.id == first.id
    assert rescheduled.schedule_version == 2
    result = await worker.dispatch(claim)
    assert result.status == "stale"
    assert channel.attempts == []
    assert channel.deliveries_for(TENANT_A_CTX) == ()


@pytest.mark.anyio
@pytest.mark.resilience
async def test_process_crash_new_engine_resumes_pending_job() -> None:
    _reset_schema()
    _seed_tenants()
    first_db = create_async_engine(DATABASE_URL)
    clock = AdjustableClock(DUE_AT)
    policy = SchedulingPolicy()
    channel = FakeChannelAdapter()
    lookup = FakeAppointmentLookup()
    lookup.set_status(TENANT_A, "appt-1", "scheduled")
    audit = InMemoryAuditSink()
    try:
        store = SqlAlchemyJobStore(first_db)
        scheduler = ReminderScheduler(store=store, clock=clock, policy=policy)
        await scheduler.upsert(
            TENANT_A_CTX,
            AppointmentScheduledEvent(
                appointment_id="appt-1", starts_at=STARTS_AT
            ),
        )
    finally:
        await first_db.dispose()

    second_db = create_async_engine(DATABASE_URL)
    try:
        store = SqlAlchemyJobStore(second_db)
        worker = JobWorker(
            store=store,
            clock=clock,
            channel=channel,
            lookup=lookup,
            policy=policy,
            audit=audit,
            owner="worker-restart",
        )
        claim = await worker.claim()
        assert claim is not None
        result = await worker.dispatch(claim)
        assert result.status == "dispatched"
        assert len(channel.deliveries_for(TENANT_A_CTX)) == 1
        loaded = await store.get_by_identity(
            TENANT_A_CTX, "appointment_reminder", "appt-1:pre_appointment"
        )
        assert loaded is not None
        assert loaded.status == "dispatched"
    finally:
        await second_db.dispose()


@pytest.mark.anyio
@pytest.mark.resilience
async def test_tenant_b_status_does_not_skip_tenant_a_job(
    db: AsyncEngine,
) -> None:
    scheduler, worker, store, _clock, channel, lookup, _audit, _policy = _stack(
        db
    )
    lookup.set_status(TENANT_A, "appt-shared", "scheduled")
    lookup.set_status(TENANT_B, "appt-shared", "cancelled")
    job_a = await scheduler.upsert(
        TENANT_A_CTX,
        AppointmentScheduledEvent(
            appointment_id="appt-shared", starts_at=STARTS_AT
        ),
    )
    job_b = await scheduler.upsert(
        TENANT_B_CTX,
        AppointmentScheduledEvent(
            appointment_id="appt-shared", starts_at=STARTS_AT
        ),
    )
    results = []
    while True:
        claim = await worker.claim()
        if claim is None:
            break
        results.append(await worker.dispatch(claim))
    by_tenant = {item.job.tenant_id: item for item in results}
    assert by_tenant[TENANT_A].status == "dispatched"
    assert by_tenant[TENANT_B].status == "skipped"
    assert channel.tenant_ids_used() == (TENANT_A,)
    assert await store.get(TENANT_B, job_a.id) is None
    assert await store.get(TENANT_A, job_b.id) is None
    assert channel.deliveries_for(TENANT_B_CTX) == ()
