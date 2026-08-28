from collections.abc import Mapping
from dataclasses import replace
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from ia_mcp.observability.context import bind_correlation_id, reset_correlation_id
from ia_mcp.observability.propagation import (
    bind_telemetry,
    extract_payload,
    inject_payload,
    last_span_id_from_payload,
    reset_telemetry,
    start_span,
)
from ia_mcp.observability.semconv import SPAN_SCHEDULER_DISPATCH
from ia_mcp.scheduling.models import (
    JOB_TYPE,
    DispatchResult,
    JobClaim,
    JobStatus,
    OutboundReminder,
    ScheduledJob,
    SchedulingOutbox,
    SchedulingPolicy,
)
from ia_mcp.scheduling.ports import (
    AppointmentLookup,
    AuditSink,
    ChannelAdapter,
    Clock,
    JobStore,
)
from ia_mcp.tenancy.models import TenantContext

_SKIP_STATUSES = frozenset({"confirmed", "cancelled"})
_ACTION = "appointment_reminder.dispatch"
_ERROR_MAX_LEN = 512


def _bound_error(error: str | None) -> str | None:
    if error is None:
        return None
    if len(error) <= _ERROR_MAX_LEN:
        return error
    return error[:_ERROR_MAX_LEN]


def _payload_str(payload: Mapping[str, object], key: str, default: str) -> str:
    value = payload.get(key)
    if isinstance(value, str) and value:
        return value
    return default


def _tenant_from_job(job: ScheduledJob) -> TenantContext:
    payload = job.payload
    slug = _payload_str(payload, "tenant_slug", "unknown")
    raw_version = payload.get("config_version")
    config_version = raw_version if isinstance(raw_version, int) else 1
    raw_corr = payload.get("correlation_id")
    try:
        correlation_id = UUID(str(raw_corr)) if raw_corr is not None else job.id
    except ValueError:
        correlation_id = job.id
    return TenantContext(
        tenant_id=job.tenant_id,
        tenant_slug=slug,
        config_version=config_version,
        correlation_id=correlation_id,
    )


def _appointment_id(payload: Mapping[str, object]) -> str:
    return _payload_str(payload, "appointment_id", "")


def _is_skip_status(status: str | None) -> bool:
    if status is None:
        return False
    return status.strip().lower() in _SKIP_STATUSES


def _outbound(job: ScheduledJob, appointment_id: str) -> OutboundReminder:
    return OutboundReminder(
        job_id=job.id,
        appointment_id=appointment_id,
        reminder_kind=_payload_str(job.payload, "reminder_kind", "pre_appointment"),
        scheduled_for=job.scheduled_for,
        schedule_version=job.schedule_version,
        external_message_id=f"reminder:{job.id}:{job.schedule_version}",
        text="Reminder: you have an upcoming appointment.",
    )


class JobWorker:
    def __init__(
        self,
        store: JobStore,
        clock: Clock,
        channel: ChannelAdapter,
        lookup: AppointmentLookup,
        policy: SchedulingPolicy,
        audit: AuditSink,
        owner: str,
        lock_ttl: timedelta = timedelta(minutes=5),
    ) -> None:
        self._store = store
        self._clock = clock
        self._channel = channel
        self._lookup = lookup
        self._policy = policy
        self._audit = audit
        self._owner = owner
        self._lock_ttl = lock_ttl

    async def claim(self) -> JobClaim | None:
        now = self._clock.now()
        job = await self._store.claim_due(
            now=now, owner=self._owner, lock_until=now + self._lock_ttl
        )
        if job is None:
            return None
        return JobClaim(
            job=job,
            schedule_version=job.schedule_version,
            owner=job.lock_owner or self._owner,
        )

    async def dispatch(self, claim: JobClaim) -> DispatchResult:
        context = extract_payload(claim.job.payload)
        telemetry_token = bind_telemetry(context)
        correlation_token = bind_correlation_id(context.correlation_id)
        previous = last_span_id_from_payload(claim.job.payload)
        links: tuple[tuple[str, str], ...] = ()
        if claim.job.attempts > 0 and previous is not None:
            links = ((context.trace_id, previous),)
        try:
            with start_span(
                SPAN_SCHEDULER_DISPATCH,
                attributes={"retry_count": claim.job.attempts},
                links=links,
            ) as span:
                result = await self._dispatch_job(claim)
                span.attributes["status"] = result.status
                return result
        finally:
            reset_correlation_id(correlation_token)
            reset_telemetry(telemetry_token)

    async def _dispatch_job(self, claim: JobClaim) -> DispatchResult:
        now = self._clock.now()
        tenant = _tenant_from_job(claim.job)
        job = await self._store.get(tenant, claim.job.id)
        if job is None or job.schedule_version != claim.schedule_version:
            return DispatchResult(
                status="stale",
                job=job if job is not None else claim.job,
                reason="stale_schedule_version",
            )
        if await self._store.has_outbox(
            tenant, job.id, job.schedule_version
        ):
            saved = await self._finish(job, "dispatched", now)
            return DispatchResult(status="dispatched", job=saved, reason="replay")
        lock_expired = (
            job.lock_expires_at is None or job.lock_expires_at <= now
        )
        if (
            job.lock_owner != claim.owner
            or lock_expired
            or job.status != "claimed"
        ):
            return DispatchResult(status="stale", job=job, reason="stale_claim")
        appointment_id = _appointment_id(job.payload)
        appt_status = await self._lookup.status(tenant, appointment_id)
        if _is_skip_status(appt_status):
            saved = await self._finish(job, "skipped", now)
            await self._record(tenant, saved, outcome="skipped", reason=appt_status)
            return DispatchResult(status="skipped", job=saved, reason=appt_status)
        reminder = _outbound(job, appointment_id)
        result = await self._channel.send(tenant, reminder)
        if result.ok:
            external_id = result.external_message_id or reminder.external_message_id
            await self._store.put_outbox(
                SchedulingOutbox(
                    tenant_id=job.tenant_id,
                    id=uuid4(),
                    job_id=job.id,
                    schedule_version=job.schedule_version,
                    kind=JOB_TYPE,
                    payload=inject_payload(dict(job.payload)),
                    external_message_id=external_id,
                    created_at=now,
                )
            )
            saved = await self._finish(job, "dispatched", now)
            await self._record(tenant, saved, outcome="dispatched")
            return DispatchResult(status="dispatched", job=saved)
        attempts = job.attempts + 1
        last_error = _bound_error(result.error or "channel_unavailable")
        if attempts < self._policy.max_attempts:
            saved = replace(
                job,
                status="pending",
                attempts=attempts,
                last_error=last_error,
                lock_owner=None,
                lock_expires_at=None,
                updated_at=now,
                payload=inject_payload(dict(job.payload)),
            )
            saved = await self._store.save(saved)
            await self._record(tenant, saved, outcome="retry", reason=last_error)
            return DispatchResult(status="retry", job=saved, reason=last_error)
        saved = replace(
            job,
            status="failed",
            attempts=attempts,
            last_error=last_error,
            lock_owner=None,
            lock_expires_at=None,
            updated_at=now,
        )
        saved = await self._store.save(saved)
        await self._record(tenant, saved, outcome="failed", reason=last_error)
        return DispatchResult(status="failed", job=saved, reason=last_error)

    async def _finish(
        self, job: ScheduledJob, status: JobStatus, now: datetime
    ) -> ScheduledJob:
        updated = replace(
            job,
            status=status,
            lock_owner=None,
            lock_expires_at=None,
            updated_at=now,
        )
        return await self._store.save(updated)

    async def _record(
        self,
        tenant: TenantContext,
        job: ScheduledJob,
        *,
        outcome: str,
        reason: str | None = None,
    ) -> None:
        await self._audit.record(
            tenant,
            action=_ACTION,
            resource_type="scheduled_job",
            resource_id=str(job.id),
            outcome=outcome,
            reason=reason,
            metadata={
                "attempts": job.attempts,
                "schedule_version": job.schedule_version,
                "job_type": job.type,
            },
        )
