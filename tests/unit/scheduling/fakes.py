from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import replace
from datetime import datetime, timedelta
from uuid import UUID

from ia_mcp.scheduling.models import (
    DeliveryResult,
    OutboundReminder,
    ScheduledJob,
    SchedulingOutbox,
)
from ia_mcp.tenancy.models import TenantContext


class AdjustableClock:
    def __init__(self, instant: datetime) -> None:
        self._now = instant

    def now(self) -> datetime:
        return self._now

    def set(self, instant: datetime) -> None:
        self._now = instant

    def advance(self, delta: timedelta) -> None:
        self._now = self._now + delta


class InMemoryJobStore:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._jobs: dict[tuple[UUID, UUID], ScheduledJob] = {}
        self._by_identity: dict[tuple[UUID, str, str], UUID] = {}
        self._outbox: dict[tuple[UUID, UUID, int], SchedulingOutbox] = {}

    async def get(self, tenant_id: UUID, job_id: UUID) -> ScheduledJob | None:
        async with self._lock:
            return self._jobs.get((tenant_id, job_id))

    async def get_by_identity(
        self, tenant: TenantContext, job_type: str, business_key: str
    ) -> ScheduledJob | None:
        async with self._lock:
            job_id = self._by_identity.get(
                (tenant.tenant_id, job_type, business_key)
            )
            if job_id is None:
                return None
            return self._jobs.get((tenant.tenant_id, job_id))

    async def put(self, job: ScheduledJob) -> ScheduledJob:
        async with self._lock:
            identity = (job.tenant_id, job.type, job.business_key)
            existing_id = self._by_identity.get(identity)
            stored = job
            if existing_id is not None and existing_id != job.id:
                stored = replace(job, id=existing_id)
            self._jobs[(stored.tenant_id, stored.id)] = stored
            self._by_identity[identity] = stored.id
            return stored

    async def save(self, job: ScheduledJob) -> ScheduledJob:
        async with self._lock:
            self._jobs[(job.tenant_id, job.id)] = job
            self._by_identity[(job.tenant_id, job.type, job.business_key)] = job.id
            return job

    async def claim_due(
        self, *, now: datetime, owner: str, lock_until: datetime
    ) -> ScheduledJob | None:
        async with self._lock:
            due: list[ScheduledJob] = []
            for job in self._jobs.values():
                if job.scheduled_for > now:
                    continue
                if job.status == "pending":
                    due.append(job)
                    continue
                if (
                    job.status == "claimed"
                    and job.lock_expires_at is not None
                    and job.lock_expires_at <= now
                ):
                    due.append(job)
            due.sort(key=lambda item: (item.scheduled_for, str(item.id)))
            if not due:
                return None
            job = due[0]
            claimed = replace(
                job,
                status="claimed",
                lock_owner=owner,
                lock_expires_at=lock_until,
                updated_at=now,
            )
            self._jobs[(claimed.tenant_id, claimed.id)] = claimed
            return claimed

    async def put_outbox(self, event: SchedulingOutbox) -> bool:
        async with self._lock:
            key = (event.tenant_id, event.job_id, event.schedule_version)
            if key in self._outbox:
                return False
            ext = (event.tenant_id, event.external_message_id)
            for existing in self._outbox.values():
                if (
                    existing.tenant_id,
                    existing.external_message_id,
                ) == ext:
                    return False
            self._outbox[key] = event
            return True

    async def has_outbox(
        self, tenant_id: UUID, job_id: UUID, schedule_version: int
    ) -> bool:
        async with self._lock:
            return (tenant_id, job_id, schedule_version) in self._outbox

    def outbox_for(self, tenant_id: UUID) -> tuple[SchedulingOutbox, ...]:
        return tuple(
            item for item in self._outbox.values() if item.tenant_id == tenant_id
        )


class FakeChannelAdapter:
    def __init__(self, *, fail_times: int = 0, fail_forever: bool = False) -> None:
        self.fail_times = fail_times
        self.fail_forever = fail_forever
        self._failures_left = fail_times
        self.attempts: list[tuple[UUID, OutboundReminder]] = []
        self.deliveries: dict[tuple[UUID, str], OutboundReminder] = {}

    async def send(
        self, tenant: TenantContext, message: OutboundReminder
    ) -> DeliveryResult:
        self.attempts.append((tenant.tenant_id, message))
        if self.fail_forever or self._failures_left > 0:
            if self._failures_left > 0:
                self._failures_left -= 1
            return DeliveryResult(ok=False, error="channel_unavailable")
        key = (tenant.tenant_id, message.external_message_id)
        self.deliveries.setdefault(key, message)
        return DeliveryResult(
            ok=True, external_message_id=message.external_message_id
        )

    def deliveries_for(self, tenant: TenantContext) -> tuple[OutboundReminder, ...]:
        return tuple(
            message
            for (tenant_id, _), message in self.deliveries.items()
            if tenant_id == tenant.tenant_id
        )

    def tenant_ids_used(self) -> tuple[UUID, ...]:
        return tuple(tenant_id for tenant_id, _ in self.attempts)


class FakeAppointmentLookup:
    def __init__(self) -> None:
        self._status: dict[tuple[UUID, str], str] = {}
        self.lookups: list[tuple[UUID, str]] = []

    def set_status(
        self, tenant_id: UUID, appointment_id: str, status: str
    ) -> None:
        self._status[(tenant_id, appointment_id)] = status

    async def status(
        self, tenant: TenantContext, appointment_id: str
    ) -> str | None:
        self.lookups.append((tenant.tenant_id, appointment_id))
        return self._status.get((tenant.tenant_id, appointment_id))


class InMemoryAuditSink:
    def __init__(self) -> None:
        self.entries: list[Mapping[str, object]] = []

    async def record(
        self,
        tenant: TenantContext,
        *,
        action: str,
        resource_type: str,
        resource_id: str,
        outcome: str,
        reason: str | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> None:
        self.entries.append(
            {
                "tenant_id": tenant.tenant_id,
                "action": action,
                "resource_type": resource_type,
                "resource_id": resource_id,
                "outcome": outcome,
                "reason": reason,
                "metadata": dict(metadata or {}),
            }
        )
