"""AC-P07-006: correlation/trace crosses HTTP, outbox, worker and MCP."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import datetime, timedelta
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from ia_mcp.api.app import create_app
from ia_mcp.channels.outbox import ChannelOutbox, OutboundDelivery
from ia_mcp.contracts.common import ToolResult
from ia_mcp.mcp.executor import McpTarget, ToolCall, ToolExecutor
from ia_mcp.mcp.fakes.appointments import FakeAppointmentCapability
from ia_mcp.observability.context import CORRELATION_HEADER
from ia_mcp.observability.propagation import (
    TRACEPARENT_HEADER,
    TelemetryContext,
    bind_telemetry,
    configure_telemetry,
    extract,
    extract_payload,
    flush_telemetry,
    recorded_spans,
    reset_telemetry,
    reset_telemetry_context,
    sanitized_span_tree,
)
from ia_mcp.observability.semconv import (
    SPAN_CHANNEL_RECEIVE,
    SPAN_CHANNEL_SEND,
    SPAN_MCP_RESOLVE,
    SPAN_SCHEDULER_DISPATCH,
    SPAN_TOOL_EXECUTE,
)
from ia_mcp.scheduling.models import (
    AppointmentScheduledEvent,
    ScheduledJob,
    SchedulingPolicy,
)
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

TENANT = TenantContext(
    tenant_id=UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
    tenant_slug="tenant-a",
    config_version=1,
    correlation_id=UUID("33333333-3333-3333-3333-333333333333"),
)
BA = ZoneInfo("America/Argentina/Buenos_Aires")
STARTS_AT = datetime(2026, 9, 3, 12, 0, tzinfo=BA)
DUE_AT = datetime(2026, 9, 1, 12, 0, tzinfo=BA)
TOOLS = frozenset({"appointments.search"})


class _StaticResolver:
    async def resolve(self, tenant: TenantContext, capability: str) -> McpTarget:
        del tenant, capability
        return McpTarget(server_id="mcp-appointments", allowed_tools=TOOLS)


class _CorrelationAudit(InMemoryAuditSink):
    def __init__(self) -> None:
        super().__init__()
        self.correlation_ids: list[UUID] = []

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
        self.correlation_ids.append(tenant.correlation_id)
        await super().record(
            tenant,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            outcome=outcome,
            reason=reason,
            metadata=metadata,
        )


def test_single_trace_links_http_outbox_worker_and_mcp() -> None:
    configure_telemetry()
    run_id = uuid4()
    client = TestClient(create_app())
    response = client.get("/health/live")
    assert response.status_code == 200
    assert TRACEPARENT_HEADER in response.headers
    correlation_id = UUID(response.headers[CORRELATION_HEADER])
    http_ctx = extract(response.headers)
    assert http_ctx.correlation_id == correlation_id
    reset_telemetry_context()

    outbox = ChannelOutbox()
    delivery = asyncio.run(_put_outbox(http_ctx, outbox, correlation_id, run_id))
    outbox_carrier = dict(outbox.carrier_for(delivery))
    reset_telemetry_context()
    outbox_ctx = extract(outbox_carrier)
    assert outbox_ctx.trace_id == http_ctx.trace_id
    assert outbox_ctx.correlation_id == correlation_id

    store = InMemoryJobStore()
    clock = AdjustableClock(DUE_AT)
    scheduler = ReminderScheduler(store, clock, SchedulingPolicy())
    channel = FakeChannelAdapter()
    lookup = FakeAppointmentLookup()
    lookup.set_status(TENANT.tenant_id, "appt-1", "scheduled")
    audit = _CorrelationAudit()
    worker = JobWorker(
        store=store,
        clock=clock,
        channel=channel,
        lookup=lookup,
        policy=SchedulingPolicy(),
        audit=audit,
        owner="worker-1",
        lock_ttl=timedelta(minutes=5),
    )
    dispatched = asyncio.run(
        _upsert_and_dispatch(scheduler, worker, store, outbox_carrier)
    )
    reset_telemetry_context()
    events = store.outbox_for(TENANT.tenant_id)
    assert len(events) == 1
    worker_carrier = _as_carrier(events[0].payload.get("telemetry"))
    worker_ctx = extract(worker_carrier)
    assert worker_ctx.trace_id == http_ctx.trace_id
    assert worker_ctx.correlation_id == correlation_id
    payload_ctx = extract_payload(dispatched.payload)
    assert payload_ctx.correlation_id == correlation_id
    assert payload_ctx.trace_id == http_ctx.trace_id
    assert audit.correlation_ids
    assert set(audit.correlation_ids) == {correlation_id}

    mcp_carrier = dict(worker_carrier)
    result = asyncio.run(_execute_mcp(mcp_carrier, run_id))
    assert result.ok is True
    mcp_ctx = extract(mcp_carrier)
    assert mcp_ctx.trace_id == http_ctx.trace_id
    assert mcp_ctx.correlation_id == correlation_id

    flush_telemetry()
    spans = recorded_spans()
    names = {span.name for span in spans}
    assert SPAN_CHANNEL_RECEIVE in names
    assert SPAN_CHANNEL_SEND in names
    assert SPAN_SCHEDULER_DISPATCH in names
    assert SPAN_MCP_RESOLVE in names
    assert SPAN_TOOL_EXECUTE in names
    assert {span.trace_id for span in spans} == {http_ctx.trace_id}
    assert {span.correlation_id for span in spans} == {correlation_id}
    tree = sanitized_span_tree(spans)
    dumped = str(tree)
    assert "prompt" not in dumped
    assert "payload" not in dumped
    assert run_id.hex in dumped or str(run_id) in dumped


def _as_carrier(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {str(key): str(item) for key, item in value.items()}


async def _put_outbox(
    http_ctx: TelemetryContext,
    outbox: ChannelOutbox,
    correlation_id: UUID,
    run_id: UUID,
) -> OutboundDelivery:
    token = bind_telemetry(http_ctx)
    try:
        return await outbox.put(
            OutboundDelivery(
                tenant_id=TENANT.tenant_id,
                tenant_slug=TENANT.tenant_slug,
                correlation_id=correlation_id,
                config_version=TENANT.config_version,
                run_id=run_id,
                kind="faq_answer",
                text="Hours are posted on the site.",
                source_ids=("src-1",),
                external_message_id="msg-1",
            )
        )
    finally:
        reset_telemetry(token)


async def _upsert_and_dispatch(
    scheduler: ReminderScheduler,
    worker: JobWorker,
    store: InMemoryJobStore,
    carrier: dict[str, str],
) -> ScheduledJob:
    token = bind_telemetry(extract(carrier))
    try:
        job = await scheduler.upsert(
            TENANT,
            AppointmentScheduledEvent(appointment_id="appt-1", starts_at=STARTS_AT),
        )
    finally:
        reset_telemetry(token)
    assert "telemetry" in job.payload
    loaded = await store.get(TENANT, job.id)
    assert loaded is not None
    assert extract_payload(loaded.payload).trace_id == extract(carrier).trace_id
    reset_telemetry_context()
    claim = await worker.claim()
    assert claim is not None
    result = await worker.dispatch(claim)
    assert result.status == "dispatched"
    return result.job


async def _execute_mcp(carrier: dict[str, str], run_id: UUID) -> ToolResult[object]:
    executor = ToolExecutor(
        server=TOOLS,
        tenant=TOOLS,
        skill=TOOLS,
        capability=FakeAppointmentCapability(),
        resolver=_StaticResolver(),
    )
    return await executor.execute(
        TENANT,
        run_id,
        ToolCall(
            name="appointments.search",
            arguments={
                "specialty": "cardiologia",
                "date_from": "2026-09-03",
                "date_to": "2026-09-04",
            },
        ),
        carrier=carrier,
    )
