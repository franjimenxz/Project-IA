from __future__ import annotations

from datetime import datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest

from ia_mcp.scheduling.models import AppointmentScheduledEvent, SchedulingPolicy
from ia_mcp.scheduling.service import ReminderScheduler
from ia_mcp.scheduling.worker import JobWorker
from ia_mcp.tenancy.models import TenantContext
from tests.unit.scheduling.fakes import (
    AdjustableClock,
    FakeAppointmentLookup,
    FakeChannelAdapter,
    InMemoryAuditSink,
    InMemoryJobStore,
)

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


def _stack(
    *,
    policy: SchedulingPolicy | None = None,
    channel: FakeChannelAdapter | None = None,
    owner: str = "worker-1",
    lock_ttl: timedelta = timedelta(minutes=5),
) -> tuple[
    ReminderScheduler,
    JobWorker,
    InMemoryJobStore,
    AdjustableClock,
    FakeChannelAdapter,
    FakeAppointmentLookup,
    InMemoryAuditSink,
    SchedulingPolicy,
]:
    clock = AdjustableClock(DUE_AT)
    store = InMemoryJobStore()
    resolved_policy = policy or SchedulingPolicy()
    scheduler = ReminderScheduler(
        store=store, clock=clock, policy=resolved_policy
    )
    resolved_channel = channel or FakeChannelAdapter()
    lookup = FakeAppointmentLookup()
    audit = InMemoryAuditSink()
    worker = JobWorker(
        store=store,
        clock=clock,
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
        clock,
        resolved_channel,
        lookup,
        audit,
        resolved_policy,
    )


@pytest.mark.anyio
async def test_stale_schedule_version_claim_is_omitted() -> None:
    scheduler, worker, _store, _clock, channel, lookup, _audit, _policy = (
        _stack()
    )
    lookup.set_status(TENANT_A, "appt-1", "scheduled")
    job = await scheduler.upsert(
        TENANT_A_CTX,
        AppointmentScheduledEvent(appointment_id="appt-1", starts_at=STARTS_AT),
    )
    assert job.schedule_version == 1
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
    assert rescheduled.schedule_version == 2
    assert rescheduled.scheduled_for == datetime(2026, 9, 2, 12, 0, tzinfo=BA)
    result = await worker.dispatch(claim)
    assert result.status == "stale"
    assert channel.deliveries_for(TENANT_A_CTX) == ()
    assert channel.attempts == []


@pytest.mark.anyio
async def test_confirmed_and_cancelled_are_skipped_before_send() -> None:
    for status in ("confirmed", "cancelled"):
        scheduler, worker, _store, _clock, channel, lookup, _audit, _policy = (
            _stack()
        )
        lookup.set_status(TENANT_A, "appt-1", status)
        await scheduler.upsert(
            TENANT_A_CTX,
            AppointmentScheduledEvent(
                appointment_id="appt-1", starts_at=STARTS_AT
            ),
        )
        claim = await worker.claim()
        assert claim is not None
        result = await worker.dispatch(claim)
        assert result.status == "skipped"
        assert result.reason == status
        assert result.job.status == "skipped"
        assert channel.attempts == []


@pytest.mark.anyio
async def test_replay_of_same_job_version_does_not_duplicate_delivery() -> None:
    scheduler, worker, store, _clock, channel, lookup, _audit, _policy = (
        _stack()
    )
    lookup.set_status(TENANT_A, "appt-1", "scheduled")
    job = await scheduler.upsert(
        TENANT_A_CTX,
        AppointmentScheduledEvent(appointment_id="appt-1", starts_at=STARTS_AT),
    )
    claim = await worker.claim()
    assert claim is not None
    first = await worker.dispatch(claim)
    second = await worker.dispatch(claim)
    assert first.status == "dispatched"
    assert second.status == "dispatched"
    assert second.reason == "replay"
    assert len(channel.deliveries_for(TENANT_A_CTX)) == 1
    assert len(channel.attempts) == 1
    assert await store.has_outbox(TENANT_A, job.id, 1) is True


@pytest.mark.anyio
async def test_restarted_worker_resumes_pending_job() -> None:
    scheduler, worker, store, clock, channel, lookup, audit, policy = _stack(
        lock_ttl=timedelta(minutes=1)
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
async def test_channel_failure_retries_then_fails_and_is_audited() -> None:
    policy = SchedulingPolicy(max_attempts=3)
    channel = FakeChannelAdapter(fail_forever=True)
    scheduler, worker, store, clock, channel, lookup, audit, policy = _stack(
        policy=policy, channel=channel
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
    assert audit.entries[-1]["outcome"] == "failed"
    assert channel.deliveries_for(TENANT_A_CTX) == ()
    later = await worker.claim()
    assert later is None
    clock.advance(timedelta(minutes=5))
    assert await worker.claim() is None


@pytest.mark.anyio
async def test_job_of_tenant_a_never_uses_tenant_b_resources() -> None:
    scheduler, worker, _store, _clock, channel, lookup, _audit, _policy = (
        _stack()
    )
    lookup.set_status(TENANT_A, "appt-a", "scheduled")
    lookup.set_status(TENANT_B, "appt-b", "scheduled")
    lookup.set_status(TENANT_B, "appt-a", "cancelled")
    lookup.set_status(TENANT_A, "appt-b", "cancelled")
    await scheduler.upsert(
        TENANT_A_CTX,
        AppointmentScheduledEvent(appointment_id="appt-a", starts_at=STARTS_AT),
    )
    await scheduler.upsert(
        TENANT_B_CTX,
        AppointmentScheduledEvent(appointment_id="appt-b", starts_at=STARTS_AT),
    )
    first = await worker.claim()
    assert first is not None
    first_result = await worker.dispatch(first)
    second = await worker.claim()
    assert second is not None
    second_result = await worker.dispatch(second)
    assert first_result.status == "dispatched"
    assert second_result.status == "dispatched"
    assert {first_result.job.tenant_id, second_result.job.tenant_id} == {
        TENANT_A,
        TENANT_B,
    }
    assert set(channel.tenant_ids_used()) == {TENANT_A, TENANT_B}
    assert (TENANT_A, "appt-a") in lookup.lookups
    assert (TENANT_B, "appt-b") in lookup.lookups
    assert (TENANT_A, "appt-b") not in lookup.lookups
    assert (TENANT_B, "appt-a") not in lookup.lookups
