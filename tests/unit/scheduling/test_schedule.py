from __future__ import annotations

from datetime import datetime
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest

from ia_mcp.scheduling.models import AppointmentScheduledEvent, SchedulingPolicy
from ia_mcp.scheduling.service import ReminderScheduler
from ia_mcp.tenancy.models import TenantContext
from tests.unit.scheduling.fakes import AdjustableClock, InMemoryJobStore

TENANT_A = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
TENANT_A_CTX = TenantContext(
    tenant_id=TENANT_A,
    tenant_slug="tenant-a",
    config_version=1,
    correlation_id=UUID("33333333-3333-3333-3333-333333333333"),
)
BA = ZoneInfo("America/Argentina/Buenos_Aires")
STARTS_AT = datetime(2026, 9, 3, 12, 0, tzinfo=BA)


def _scheduler(
    policy: SchedulingPolicy | None = None,
) -> tuple[ReminderScheduler, InMemoryJobStore, AdjustableClock]:
    clock = AdjustableClock(datetime(2026, 8, 28, 12, 0, tzinfo=BA))
    store = InMemoryJobStore()
    scheduler = ReminderScheduler(
        store=store,
        clock=clock,
        policy=policy or SchedulingPolicy(),
    )
    return scheduler, store, clock


@pytest.mark.anyio
async def test_upsert_schedules_48h_before_in_buenos_aires_timezone() -> None:
    scheduler, _store, _clock = _scheduler()
    job = await scheduler.upsert(
        TENANT_A_CTX,
        AppointmentScheduledEvent(appointment_id="appt-1", starts_at=STARTS_AT),
    )
    assert job.scheduled_for == datetime(2026, 9, 1, 12, 0, tzinfo=BA)
    assert job.schedule_version == 1
    assert job.business_key == "appt-1:pre_appointment"
    assert job.type == "appointment_reminder"
    assert job.status == "pending"
    assert job.tenant_id == TENANT_A


@pytest.mark.anyio
async def test_different_lead_hours_changes_scheduled_for_without_code_change() -> None:
    scheduler, _store, _clock = _scheduler(SchedulingPolicy(lead_hours=24))
    job = await scheduler.upsert(
        TENANT_A_CTX,
        AppointmentScheduledEvent(appointment_id="appt-1", starts_at=STARTS_AT),
    )
    assert job.scheduled_for == datetime(2026, 9, 2, 12, 0, tzinfo=BA)
    assert job.schedule_version == 1


@pytest.mark.anyio
async def test_reupsert_replaces_schedule_and_increments_version() -> None:
    scheduler, store, _clock = _scheduler()
    first = await scheduler.upsert(
        TENANT_A_CTX,
        AppointmentScheduledEvent(appointment_id="appt-1", starts_at=STARTS_AT),
    )
    second = await scheduler.upsert(
        TENANT_A_CTX,
        AppointmentScheduledEvent(
            appointment_id="appt-1",
            starts_at=datetime(2026, 9, 4, 12, 0, tzinfo=BA),
        ),
    )
    assert second.id == first.id
    assert second.schedule_version == 2
    assert second.scheduled_for == datetime(2026, 9, 2, 12, 0, tzinfo=BA)
    assert second.status == "pending"
    loaded = await store.get_by_identity(
        TENANT_A_CTX, "appointment_reminder", "appt-1:pre_appointment"
    )
    assert loaded is not None
    assert loaded.schedule_version == 2


@pytest.mark.anyio
async def test_cancel_marks_job_so_it_will_not_send() -> None:
    scheduler, store, clock = _scheduler()
    job = await scheduler.upsert(
        TENANT_A_CTX,
        AppointmentScheduledEvent(appointment_id="appt-1", starts_at=STARTS_AT),
    )
    cancelled = await scheduler.cancel(TENANT_A_CTX, "appt-1")
    assert cancelled is not None
    assert cancelled.id == job.id
    assert cancelled.status == "cancelled"
    clock.set(datetime(2026, 9, 1, 12, 0, tzinfo=BA))
    claimed = await store.claim_due(
        now=clock.now(),
        owner="worker-1",
        lock_until=clock.now(),
    )
    assert claimed is None
