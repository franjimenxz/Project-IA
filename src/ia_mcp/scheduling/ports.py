from collections.abc import Mapping
from datetime import datetime
from typing import Protocol
from uuid import UUID

from ia_mcp.scheduling.models import (
    DeliveryResult,
    OutboundReminder,
    ScheduledJob,
    SchedulingOutbox,
)
from ia_mcp.tenancy.models import TenantContext


class Clock(Protocol):
    def now(self) -> datetime: ...


class ChannelAdapter(Protocol):
    async def send(
        self, tenant: TenantContext, message: OutboundReminder
    ) -> DeliveryResult: ...


class AppointmentLookup(Protocol):
    async def status(
        self, tenant: TenantContext, appointment_id: str
    ) -> str | None: ...


class AuditSink(Protocol):
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
    ) -> None: ...


class JobStore(Protocol):
    async def get(
        self, tenant: TenantContext, job_id: UUID
    ) -> ScheduledJob | None: ...

    async def get_by_identity(
        self, tenant: TenantContext, job_type: str, business_key: str
    ) -> ScheduledJob | None: ...

    async def put(self, job: ScheduledJob) -> ScheduledJob: ...

    async def save(self, job: ScheduledJob) -> ScheduledJob: ...

    async def claim_due(
        self, *, now: datetime, owner: str, lock_until: datetime
    ) -> ScheduledJob | None: ...

    async def put_outbox(self, event: SchedulingOutbox) -> bool: ...

    async def has_outbox(
        self, tenant: TenantContext, job_id: UUID, schedule_version: int
    ) -> bool: ...
