"""AC-P07-007: exporter failure does not change business results."""

from __future__ import annotations

import asyncio
import threading
import time
from datetime import datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from ia_mcp.mcp.executor import ToolCall, ToolExecutor
from ia_mcp.mcp.fakes.appointments import FakeAppointmentCapability
from ia_mcp.observability.propagation import (
    FailingSpanExporter,
    SpanRecord,
    configure_telemetry,
    exporter_metrics,
    flush_telemetry,
    recorded_spans,
    reset_telemetry_context,
    start_span,
)
from ia_mcp.observability.semconv import SPAN_CHANNEL_RECEIVE, SPAN_SCHEDULER_DISPATCH
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
_SLOW_EXPORT_SECONDS = 0.15
_SPAN_COUNT = 8


class SlowSpanExporter:
    def export(self, spans: tuple[SpanRecord, ...] | list[SpanRecord]) -> None:
        del spans
        time.sleep(_SLOW_EXPORT_SECONDS)


class GateSpanExporter:
    def __init__(self) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()

    def export(self, spans: tuple[SpanRecord, ...] | list[SpanRecord]) -> None:
        del spans
        self.entered.set()
        self.release.wait(timeout=5)


def test_exporter_failure_does_not_change_dispatch_or_tool_result() -> None:
    configure_telemetry(exporter=FailingSpanExporter())
    reset_telemetry_context()
    store = InMemoryJobStore()
    clock = AdjustableClock(DUE_AT)
    scheduler = ReminderScheduler(store, clock, SchedulingPolicy())
    channel = FakeChannelAdapter()
    lookup = FakeAppointmentLookup()
    lookup.set_status(TENANT.tenant_id, "appt-1", "scheduled")
    worker = JobWorker(
        store=store,
        clock=clock,
        channel=channel,
        lookup=lookup,
        policy=SchedulingPolicy(),
        audit=InMemoryAuditSink(),
        owner="worker-1",
        lock_ttl=timedelta(minutes=5),
    )
    dispatch, tool = asyncio.run(_run_business(scheduler, worker))
    assert dispatch.status == "dispatched"
    assert tool.ok is True
    assert channel.deliveries_for(TENANT)
    flush_telemetry()
    metrics = exporter_metrics()
    assert metrics["telemetry_exporter_failure"] >= 1


def test_retry_spans_share_trace_and_link_previous_attempt() -> None:
    configure_telemetry()
    reset_telemetry_context()
    store = InMemoryJobStore()
    clock = AdjustableClock(DUE_AT)
    scheduler = ReminderScheduler(store, clock, SchedulingPolicy())
    channel = FakeChannelAdapter(fail_times=1)
    lookup = FakeAppointmentLookup()
    lookup.set_status(TENANT.tenant_id, "appt-1", "scheduled")
    worker = JobWorker(
        store=store,
        clock=clock,
        channel=channel,
        lookup=lookup,
        policy=SchedulingPolicy(max_attempts=3),
        audit=InMemoryAuditSink(),
        owner="worker-1",
        lock_ttl=timedelta(minutes=5),
    )
    first, second = asyncio.run(_retry_then_succeed(scheduler, worker))
    assert first.status == "retry"
    assert second.status == "dispatched"
    flush_telemetry()
    dispatch_spans = [
        span for span in recorded_spans() if span.name == SPAN_SCHEDULER_DISPATCH
    ]
    assert len(dispatch_spans) >= 2
    assert {span.trace_id for span in dispatch_spans} == {dispatch_spans[0].trace_id}
    retry_span = dispatch_spans[1]
    first_span = dispatch_spans[0]
    assert retry_span.attributes.get("retry_count") == 1
    assert (first_span.trace_id, first_span.span_id) in retry_span.links


def test_slow_exporter_does_not_block_caller() -> None:
    configure_telemetry(exporter=SlowSpanExporter())
    reset_telemetry_context()
    started = time.monotonic()
    for _ in range(_SPAN_COUNT):
        with start_span(SPAN_CHANNEL_RECEIVE):
            pass
    elapsed = time.monotonic() - started
    assert elapsed < _SLOW_EXPORT_SECONDS * _SPAN_COUNT * 0.5


def test_exporter_overflow_drops_and_records_metric() -> None:
    gate = GateSpanExporter()
    configure_telemetry(exporter=gate, max_queue=2)
    reset_telemetry_context()
    for _ in range(6):
        with start_span(SPAN_CHANNEL_RECEIVE):
            pass
    assert gate.entered.wait(timeout=1)
    dropped = exporter_metrics()["telemetry_exporter_dropped"]
    gate.release.set()
    flush_telemetry()
    assert dropped >= 1


async def _run_business(
    scheduler: ReminderScheduler, worker: JobWorker
) -> tuple[object, object]:
    await scheduler.upsert(
        TENANT,
        AppointmentScheduledEvent(appointment_id="appt-1", starts_at=STARTS_AT),
    )
    claim = await worker.claim()
    assert claim is not None
    dispatch = await worker.dispatch(claim)
    executor = ToolExecutor(
        server=TOOLS,
        tenant=TOOLS,
        skill=TOOLS,
        capability=FakeAppointmentCapability(),
    )
    tool = await executor.execute(
        TENANT,
        TENANT.correlation_id,
        ToolCall(
            name="appointments.search",
            arguments={
                "specialty": "cardiologia",
                "date_from": "2026-09-03",
                "date_to": "2026-09-04",
            },
        ),
    )
    return dispatch, tool


async def _retry_then_succeed(
    scheduler: ReminderScheduler, worker: JobWorker
) -> tuple[object, object]:
    await scheduler.upsert(
        TENANT,
        AppointmentScheduledEvent(appointment_id="appt-1", starts_at=STARTS_AT),
    )
    first_claim = await worker.claim()
    assert first_claim is not None
    first = await worker.dispatch(first_claim)
    second_claim = await worker.claim()
    assert second_claim is not None
    second = await worker.dispatch(second_claim)
    return first, second
