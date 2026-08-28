from __future__ import annotations

from datetime import datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest

from ia_mcp.scheduling.models import AppointmentScheduledEvent, SchedulingPolicy
from ia_mcp.scheduling.service import ReminderScheduler
from ia_mcp.scheduling.worker import JobWorker
from ia_mcp.tenancy.models import TenantContext
from tests.fixtures.faults import (
    InjectedFault,
    InstrumentedChannel,
    instrument_channel,
    new_controller,
)
from tests.unit.scheduling.fakes import (
    AdjustableClock,
    FakeAppointmentLookup,
    FakeChannelAdapter,
    InMemoryAuditSink,
    InMemoryJobStore,
)

pytestmark = [pytest.mark.anyio, pytest.mark.resilience]

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


def _stack(
    *,
    channel: FakeChannelAdapter | InstrumentedChannel | None = None,
    policy: SchedulingPolicy | None = None,
    clock: AdjustableClock | None = None,
    owner: str = "worker-1",
    lock_ttl: timedelta = timedelta(minutes=5),
) -> tuple[
    ReminderScheduler,
    JobWorker,
    InMemoryJobStore,
    AdjustableClock,
    FakeChannelAdapter | InstrumentedChannel,
    FakeAppointmentLookup,
    InMemoryAuditSink,
    SchedulingPolicy,
]:
    store = InMemoryJobStore()
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


async def test_claimed_job_recovers_after_worker_restart() -> None:
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


async def test_channel_before_send_fault_then_recovery_is_single_delivery() -> None:
    controller = new_controller(
        InjectedFault(
            dependency="channel", boundary="before", kind="unavailable", times=2
        )
    )
    channel = instrument_channel(FakeChannelAdapter(), controller)
    policy = SchedulingPolicy(max_attempts=3)
    scheduler, worker, store, _clock, _ch, lookup, audit, _policy = _stack(
        channel=channel, policy=policy
    )
    lookup.set_status(TENANT_A, "appt-1", "scheduled")
    job = await scheduler.upsert(
        TENANT_A_CTX,
        AppointmentScheduledEvent(appointment_id="appt-1", starts_at=STARTS_AT),
    )
    statuses = []
    for _ in range(3):
        claim = await worker.claim()
        assert claim is not None
        statuses.append((await worker.dispatch(claim)).status)
    assert statuses == ["retry", "retry", "dispatched"]
    loaded = await store.get(TENANT_A_CTX, job.id)
    assert loaded is not None
    assert loaded.status == "dispatched"
    assert len(channel.deliveries_for(TENANT_A_CTX)) == 1
    assert controller.side_effect_count("channel.send") == 1
    assert audit.entries[-1]["outcome"] == "dispatched"


async def _require_claim(worker: JobWorker):
    claim = await worker.claim()
    assert claim is not None
    return claim


async def test_channel_after_send_fault_recovers_without_duplicate() -> None:
    controller = new_controller(
        InjectedFault(
            dependency="channel", boundary="after", kind="unavailable", times=1
        )
    )
    channel = instrument_channel(FakeChannelAdapter(), controller)
    policy = SchedulingPolicy(max_attempts=3)
    scheduler, worker, _store, _clock, _ch, lookup, audit, _policy = _stack(
        channel=channel, policy=policy
    )
    lookup.set_status(TENANT_A, "appt-1", "scheduled")
    await scheduler.upsert(
        TENANT_A_CTX,
        AppointmentScheduledEvent(appointment_id="appt-1", starts_at=STARTS_AT),
    )
    first = await worker.dispatch(await _require_claim(worker))
    assert first.status == "retry"
    assert controller.side_effect_count("channel.send") == 1
    second = await worker.dispatch(await _require_claim(worker))
    assert second.status == "dispatched"
    assert len(channel.deliveries_for(TENANT_A_CTX)) == 1
    assert audit.entries[-1]["outcome"] == "dispatched"


async def test_outbox_replay_after_crash_does_not_resend() -> None:
    scheduler, worker, store, clock, channel, lookup, audit, policy = _stack()
    lookup.set_status(TENANT_A, "appt-1", "scheduled")
    await scheduler.upsert(
        TENANT_A_CTX,
        AppointmentScheduledEvent(appointment_id="appt-1", starts_at=STARTS_AT),
    )
    first = await worker.dispatch(await _require_claim(worker))
    assert first.status == "dispatched"
    clock.advance(timedelta(minutes=5))
    restarted = JobWorker(
        store=store,
        clock=clock,
        channel=channel,
        lookup=lookup,
        policy=policy,
        audit=audit,
        owner="worker-restart",
    )
    claim = await restarted.claim()
    assert claim is None
    assert len(channel.deliveries_for(TENANT_A_CTX)) == 1
