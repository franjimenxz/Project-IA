from dataclasses import replace
from datetime import datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy import (
    Column,
    DateTime,
    Integer,
    MetaData,
    PrimaryKeyConstraint,
    String,
    Table,
    UniqueConstraint,
    and_,
    or_,
    select,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from ia_mcp.scheduling.models import (
    JOB_TYPE,
    AppointmentScheduledEvent,
    JobStatus,
    ScheduledJob,
    SchedulingOutbox,
    SchedulingPolicy,
)
from ia_mcp.scheduling.ports import Clock, JobStore
from ia_mcp.tenancy.models import TenantContext

metadata = MetaData()

scheduled_job_table = Table(
    "scheduled_job",
    metadata,
    Column("tenant_id", PGUUID(as_uuid=True), nullable=False),
    Column("id", PGUUID(as_uuid=True), nullable=False),
    Column("type", String(64), nullable=False),
    Column("payload", JSONB, nullable=False),
    Column("business_key", String(255), nullable=False),
    Column("scheduled_for", DateTime(timezone=True), nullable=False),
    Column("schedule_version", Integer, nullable=False),
    Column("status", String(32), nullable=False),
    Column("attempts", Integer, nullable=False),
    Column("lock_owner", String(255), nullable=True),
    Column("lock_expires_at", DateTime(timezone=True), nullable=True),
    Column("last_error", String(512), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    PrimaryKeyConstraint("tenant_id", "id"),
    UniqueConstraint(
        "tenant_id",
        "type",
        "business_key",
        name="uq_scheduled_job_identity",
    ),
)

scheduling_outbox_table = Table(
    "scheduling_outbox",
    metadata,
    Column("tenant_id", PGUUID(as_uuid=True), nullable=False),
    Column("id", PGUUID(as_uuid=True), nullable=False),
    Column("job_id", PGUUID(as_uuid=True), nullable=False),
    Column("schedule_version", Integer, nullable=False),
    Column("external_message_id", String(255), nullable=False),
    Column("payload", JSONB, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    PrimaryKeyConstraint("tenant_id", "id"),
    UniqueConstraint(
        "tenant_id",
        "job_id",
        "schedule_version",
        name="uq_scheduling_outbox_version",
    ),
    UniqueConstraint(
        "tenant_id",
        "external_message_id",
        name="uq_scheduling_outbox_external",
    ),
)


def _payload(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    return {str(key): item for key, item in value.items()}


def _job_from_row(row: Any) -> ScheduledJob:
    return ScheduledJob(
        tenant_id=row["tenant_id"],
        id=row["id"],
        type=str(row["type"]),
        payload=_payload(row["payload"]),
        business_key=str(row["business_key"]),
        scheduled_for=row["scheduled_for"],
        schedule_version=int(row["schedule_version"]),
        status=cast(JobStatus, row["status"]),
        attempts=int(row["attempts"]),
        lock_owner=row["lock_owner"],
        lock_expires_at=row["lock_expires_at"],
        last_error=row["last_error"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _job_values(job: ScheduledJob) -> dict[str, object]:
    return {
        "tenant_id": job.tenant_id,
        "id": job.id,
        "type": job.type,
        "payload": dict(job.payload),
        "business_key": job.business_key,
        "scheduled_for": job.scheduled_for,
        "schedule_version": job.schedule_version,
        "status": job.status,
        "attempts": job.attempts,
        "lock_owner": job.lock_owner,
        "lock_expires_at": job.lock_expires_at,
        "last_error": job.last_error,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
    }


def _outbox_values(event: SchedulingOutbox) -> dict[str, object]:
    return {
        "tenant_id": event.tenant_id,
        "id": event.id,
        "job_id": event.job_id,
        "schedule_version": event.schedule_version,
        "external_message_id": event.external_message_id,
        "payload": dict(event.payload),
        "created_at": event.created_at,
    }


def _business_key(event: AppointmentScheduledEvent) -> str:
    return f"{event.appointment_id}:{event.reminder_kind}"


def _event_payload(
    tenant: TenantContext, event: AppointmentScheduledEvent
) -> dict[str, object]:
    return {
        "appointment_id": event.appointment_id,
        "starts_at": event.starts_at.isoformat(),
        "reminder_kind": event.reminder_kind,
        "status": event.status,
        "tenant_slug": tenant.tenant_slug,
        "config_version": tenant.config_version,
        "correlation_id": str(tenant.correlation_id),
    }


class ReminderScheduler:
    def __init__(
        self, store: JobStore, clock: Clock, policy: SchedulingPolicy
    ) -> None:
        self._store = store
        self._clock = clock
        self._policy = policy

    async def upsert(
        self, tenant: TenantContext, event: AppointmentScheduledEvent
    ) -> ScheduledJob:
        now = self._clock.now()
        scheduled_for = event.starts_at - timedelta(hours=self._policy.lead_hours)
        business_key = _business_key(event)
        payload = _event_payload(tenant, event)
        existing = await self._store.get_by_identity(tenant, JOB_TYPE, business_key)
        if existing is None:
            job = ScheduledJob(
                tenant_id=tenant.tenant_id,
                id=uuid4(),
                type=JOB_TYPE,
                payload=payload,
                business_key=business_key,
                scheduled_for=scheduled_for,
                schedule_version=1,
                status="pending",
                attempts=0,
                lock_owner=None,
                lock_expires_at=None,
                last_error=None,
                created_at=now,
                updated_at=now,
            )
            return await self._store.put(job)
        updated = replace(
            existing,
            payload=payload,
            scheduled_for=scheduled_for,
            schedule_version=existing.schedule_version + 1,
            status="pending",
            attempts=0,
            lock_owner=None,
            lock_expires_at=None,
            last_error=None,
            updated_at=now,
        )
        return await self._store.put(updated)

    async def cancel(
        self,
        tenant: TenantContext,
        appointment_id: str,
        *,
        reminder_kind: str = "pre_appointment",
    ) -> ScheduledJob | None:
        business_key = f"{appointment_id}:{reminder_kind}"
        existing = await self._store.get_by_identity(tenant, JOB_TYPE, business_key)
        if existing is None:
            return None
        now = self._clock.now()
        cancelled = replace(
            existing,
            status="cancelled",
            lock_owner=None,
            lock_expires_at=None,
            updated_at=now,
        )
        return await self._store.save(cancelled)


class SqlAlchemyJobStore:
    def __init__(self, engine: AsyncEngine) -> None:
        self._session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def get(
        self, tenant: TenantContext, job_id: UUID
    ) -> ScheduledJob | None:
        async with self._session_factory() as session:
            row = (
                (
                    await session.execute(
                        select(scheduled_job_table).where(
                            scheduled_job_table.c.tenant_id == tenant.tenant_id,
                            scheduled_job_table.c.id == job_id,
                        )
                    )
                )
                .mappings()
                .first()
            )
            if row is None:
                return None
            return _job_from_row(row)

    async def get_by_identity(
        self, tenant: TenantContext, job_type: str, business_key: str
    ) -> ScheduledJob | None:
        async with self._session_factory() as session:
            row = (
                (
                    await session.execute(
                        select(scheduled_job_table).where(
                            scheduled_job_table.c.tenant_id == tenant.tenant_id,
                            scheduled_job_table.c.type == job_type,
                            scheduled_job_table.c.business_key == business_key,
                        )
                    )
                )
                .mappings()
                .first()
            )
            if row is None:
                return None
            return _job_from_row(row)

    async def put(self, job: ScheduledJob) -> ScheduledJob:
        async with self._session_factory() as session, session.begin():
            existing = (
                (
                    await session.execute(
                        select(scheduled_job_table).where(
                            scheduled_job_table.c.tenant_id == job.tenant_id,
                            scheduled_job_table.c.type == job.type,
                            scheduled_job_table.c.business_key == job.business_key,
                        )
                    )
                )
                .mappings()
                .first()
            )
            stored = job
            if existing is not None and existing["id"] != job.id:
                stored = replace(job, id=existing["id"])
            values = _job_values(stored)
            if existing is None:
                await session.execute(scheduled_job_table.insert().values(**values))
            else:
                await session.execute(
                    scheduled_job_table.update()
                    .where(
                        scheduled_job_table.c.tenant_id == stored.tenant_id,
                        scheduled_job_table.c.id == stored.id,
                    )
                    .values(**values)
                )
            return stored

    async def save(self, job: ScheduledJob) -> ScheduledJob:
        values = _job_values(job)
        async with self._session_factory() as session, session.begin():
            result = await session.execute(
                scheduled_job_table.update()
                .where(
                    scheduled_job_table.c.tenant_id == job.tenant_id,
                    scheduled_job_table.c.id == job.id,
                )
                .values(**values)
            )
            if result.rowcount == 0:
                await session.execute(scheduled_job_table.insert().values(**values))
            return job

    async def claim_due(
        self, *, now: datetime, owner: str, lock_until: datetime
    ) -> ScheduledJob | None:
        async with self._session_factory() as session, session.begin():
            row = (
                (
                    await session.execute(
                        select(scheduled_job_table)
                        .where(
                            scheduled_job_table.c.scheduled_for <= now,
                            or_(
                                scheduled_job_table.c.status == "pending",
                                and_(
                                    scheduled_job_table.c.status == "claimed",
                                    scheduled_job_table.c.lock_expires_at <= now,
                                ),
                            ),
                        )
                        .order_by(
                            scheduled_job_table.c.scheduled_for,
                            scheduled_job_table.c.id,
                        )
                        .limit(1)
                        .with_for_update(skip_locked=True)
                    )
                )
                .mappings()
                .first()
            )
            if row is None:
                return None
            await session.execute(
                scheduled_job_table.update()
                .where(
                    scheduled_job_table.c.tenant_id == row["tenant_id"],
                    scheduled_job_table.c.id == row["id"],
                )
                .values(
                    status="claimed",
                    lock_owner=owner,
                    lock_expires_at=lock_until,
                    updated_at=now,
                )
            )
            job = _job_from_row(row)
            return replace(
                job,
                status="claimed",
                lock_owner=owner,
                lock_expires_at=lock_until,
                updated_at=now,
            )

    async def put_outbox(self, event: SchedulingOutbox) -> bool:
        try:
            async with self._session_factory() as session, session.begin():
                await session.execute(
                    scheduling_outbox_table.insert().values(**_outbox_values(event))
                )
            return True
        except IntegrityError:
            return False

    async def has_outbox(
        self, tenant: TenantContext, job_id: UUID, schedule_version: int
    ) -> bool:
        async with self._session_factory() as session:
            value = (
                await session.execute(
                    select(scheduling_outbox_table.c.id).where(
                        scheduling_outbox_table.c.tenant_id == tenant.tenant_id,
                        scheduling_outbox_table.c.job_id == job_id,
                        scheduling_outbox_table.c.schedule_version
                        == schedule_version,
                    )
                )
            ).first()
            return value is not None
