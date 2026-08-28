from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

type JobStatus = Literal[
    "pending",
    "claimed",
    "dispatched",
    "cancelled",
    "failed",
    "skipped",
]
type JobType = Literal["appointment_reminder"]

JOB_TYPE: JobType = "appointment_reminder"
PAYLOAD_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class SchedulingPolicy:
    lead_hours: int = 48
    timezone: str = "America/Argentina/Buenos_Aires"
    max_attempts: int = 3


@dataclass(frozen=True, slots=True)
class AppointmentScheduledEvent:
    appointment_id: str
    starts_at: datetime
    reminder_kind: str = "pre_appointment"
    status: str = "scheduled"


@dataclass(frozen=True, slots=True)
class ScheduledJob:
    tenant_id: UUID
    id: UUID
    type: str
    payload: Mapping[str, object]
    business_key: str
    scheduled_for: datetime
    schedule_version: int
    status: JobStatus
    attempts: int
    lock_owner: str | None
    lock_expires_at: datetime | None
    last_error: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class JobClaim:
    job: ScheduledJob
    schedule_version: int
    owner: str


@dataclass(frozen=True, slots=True)
class DispatchResult:
    status: str
    job: ScheduledJob
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class OutboundReminder:
    job_id: UUID
    appointment_id: str
    reminder_kind: str
    scheduled_for: datetime
    schedule_version: int
    external_message_id: str
    text: str


@dataclass(frozen=True, slots=True)
class DeliveryResult:
    ok: bool
    external_message_id: str | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class SchedulingOutbox:
    tenant_id: UUID
    id: UUID
    job_id: UUID
    schedule_version: int
    kind: str
    payload: Mapping[str, object]
    external_message_id: str
    created_at: datetime
