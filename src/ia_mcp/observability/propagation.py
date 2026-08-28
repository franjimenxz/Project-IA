from __future__ import annotations

import queue
import re
import threading
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from typing import Protocol
from uuid import UUID, uuid4

from ia_mcp.observability.redaction import redact
from ia_mcp.observability.semconv import (
    CORRELATION_HEADER,
    LAST_SPAN_ID_KEY,
    TELEMETRY_PAYLOAD_KEY,
    TRACEPARENT_HEADER,
    span_attributes,
)

_TRACEPARENT_PATTERN = r"^00-([0-9a-f]{32})-([0-9a-f]{16})-([0-9a-f]{2})$"


class MutableCarrier(Protocol):
    def __setitem__(self, key: str, value: str) -> None: ...


@dataclass(frozen=True, slots=True)
class TelemetryContext:
    trace_id: str
    span_id: str
    correlation_id: UUID
    trace_flags: str = "01"
    parent_span_id: str | None = None


_telemetry: ContextVar[TelemetryContext | None] = ContextVar(
    "ia_mcp_telemetry", default=None
)


@dataclass(slots=True)
class SpanRecord:
    name: str
    trace_id: str
    span_id: str
    parent_span_id: str | None
    correlation_id: UUID
    attributes: dict[str, object]
    links: tuple[tuple[str, str], ...] = ()

    def set_attribute(self, key: str, value: object) -> None:
        self.attributes.update(span_attributes({key: value}))


class SpanExporter:
    def export(self, spans: Sequence[SpanRecord]) -> None:
        raise NotImplementedError


class InMemorySpanExporter(SpanExporter):
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.spans: list[SpanRecord] = []

    def export(self, spans: Sequence[SpanRecord]) -> None:
        with self._lock:
            self.spans.extend(spans)

    def snapshot(self) -> tuple[SpanRecord, ...]:
        with self._lock:
            return tuple(self.spans)


class FailingSpanExporter(SpanExporter):
    def export(self, spans: Sequence[SpanRecord]) -> None:
        raise RuntimeError("exporter_unavailable")


class BoundedExporter:
    def __init__(
        self,
        inner: SpanExporter,
        *,
        max_queue: int = 256,
        metrics: dict[str, int] | None = None,
    ) -> None:
        self._inner = inner
        self._queue: queue.Queue[SpanRecord] = queue.Queue(maxsize=max_queue)
        self.metrics = metrics if metrics is not None else {
            "telemetry_exporter_failure": 0,
            "telemetry_exporter_dropped": 0,
        }
        self._metrics_lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._run, name="ia-mcp-telemetry", daemon=True
        )
        self._thread.start()

    def _bump(self, name: str) -> None:
        with self._metrics_lock:
            self.metrics[name] = self.metrics.get(name, 0) + 1

    def emit(self, span: SpanRecord) -> None:
        try:
            self._queue.put_nowait(span)
        except queue.Full:
            self._bump("telemetry_exporter_dropped")
        except Exception:  # noqa: BLE001 - exporter must never block callers
            self._bump("telemetry_exporter_failure")

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                item = self._queue.get(timeout=0.05)
            except queue.Empty:
                continue
            try:
                self._inner.export((item,))
            except Exception:  # noqa: BLE001 - local metric, no business abort
                self._bump("telemetry_exporter_failure")
            finally:
                self._queue.task_done()

    def flush(self, timeout: float = 2.0) -> None:
        done = threading.Event()

        def wait() -> None:
            self._queue.join()
            done.set()

        threading.Thread(target=wait, name="ia-mcp-telemetry-flush", daemon=True).start()
        if not done.wait(timeout):
            raise TimeoutError("telemetry exporter flush exceeded timeout")

    def snapshot_metrics(self) -> dict[str, int]:
        with self._metrics_lock:
            return dict(self.metrics)

    def shutdown(self) -> None:
        self._stop.set()
        self._thread.join(timeout=1.0)


@dataclass
class _Runtime:
    exporter: BoundedExporter
    inner: SpanExporter
    metrics: dict[str, int] = field(default_factory=dict)


_runtime: _Runtime | None = None


def _ensure_runtime() -> _Runtime:
    if _runtime is None:
        configure_telemetry()
    assert _runtime is not None
    return _runtime


def configure_telemetry(
    *,
    exporter: SpanExporter | None = None,
    max_queue: int = 256,
) -> BoundedExporter:
    global _runtime
    if _runtime is not None:
        _runtime.exporter.shutdown()
    inner = exporter if exporter is not None else InMemorySpanExporter()
    metrics = {
        "telemetry_exporter_failure": 0,
        "telemetry_exporter_dropped": 0,
    }
    bounded = BoundedExporter(inner, max_queue=max_queue, metrics=metrics)
    _runtime = _Runtime(exporter=bounded, inner=inner, metrics=metrics)
    reset_telemetry_context()
    return bounded


def flush_telemetry(timeout: float = 2.0) -> None:
    _ensure_runtime().exporter.flush(timeout=timeout)


def recorded_spans() -> tuple[SpanRecord, ...]:
    inner = _ensure_runtime().inner
    if isinstance(inner, InMemorySpanExporter):
        return inner.snapshot()
    return ()


def exporter_metrics() -> dict[str, int]:
    return _ensure_runtime().exporter.snapshot_metrics()


def current_telemetry() -> TelemetryContext | None:
    return _telemetry.get()


def bind_telemetry(context: TelemetryContext) -> Token[TelemetryContext | None]:
    return _telemetry.set(context)


def reset_telemetry(token: Token[TelemetryContext | None]) -> None:
    _telemetry.reset(token)


def reset_telemetry_context() -> None:
    _telemetry.set(None)


def _carrier_value(carrier: Mapping[str, object], name: str) -> str | None:
    target = name.lower()
    for key, value in carrier.items():
        if key.lower() == target and value is not None:
            text = str(value).strip()
            if text:
                return text
    return None


def _new_trace_id() -> str:
    value = uuid4().hex
    if value == "0" * 32:
        return "1" * 32
    return value


def _new_span_id() -> str:
    value = uuid4().hex[:16]
    if value == "0" * 16:
        return "1" * 16
    return value


def _parse_correlation(raw: str | None) -> UUID:
    if raw is None or raw.strip() == "":
        return uuid4()
    try:
        return UUID(raw)
    except ValueError:
        return uuid4()


def _new_context(correlation_id: UUID) -> TelemetryContext:
    return TelemetryContext(
        trace_id=_new_trace_id(),
        span_id=_new_span_id(),
        correlation_id=correlation_id,
    )


def new_server_context() -> TelemetryContext:
    """Mint a correlation/trace that is not derived from untrusted inbound headers."""
    return _new_context(uuid4())


def extract(carrier: Mapping[str, object]) -> TelemetryContext:
    correlation_id = _parse_correlation(
        _carrier_value(carrier, CORRELATION_HEADER)
        or _carrier_value(carrier, "x-correlation-id")
    )
    raw_parent = _carrier_value(carrier, TRACEPARENT_HEADER)
    if raw_parent is None:
        return _new_context(correlation_id)
    matched = re.fullmatch(_TRACEPARENT_PATTERN, raw_parent.lower())
    if matched is None:
        return _new_context(correlation_id)
    trace_id, span_id, flags = matched.group(1), matched.group(2), matched.group(3)
    if trace_id == "0" * 32 or span_id == "0" * 16:
        return _new_context(correlation_id)
    return TelemetryContext(
        trace_id=trace_id,
        span_id=span_id,
        correlation_id=correlation_id,
        trace_flags=flags,
    )


def format_traceparent(context: TelemetryContext) -> str:
    return f"00-{context.trace_id}-{context.span_id}-{context.trace_flags}"


def inject(
    carrier: MutableCarrier,
    context: TelemetryContext | None = None,
) -> None:
    current = context if context is not None else _telemetry.get()
    if current is None:
        return
    carrier[TRACEPARENT_HEADER] = format_traceparent(current)
    carrier[CORRELATION_HEADER] = str(current.correlation_id)
    carrier[LAST_SPAN_ID_KEY] = current.span_id


def inject_payload(payload: Mapping[str, object]) -> dict[str, object]:
    carrier: dict[str, str] = {}
    inject(carrier)
    out = dict(payload)
    if not carrier:
        return out
    out[TELEMETRY_PAYLOAD_KEY] = carrier
    current = _telemetry.get()
    if current is not None:
        out["correlation_id"] = str(current.correlation_id)
    return out


def extract_payload(payload: Mapping[str, object]) -> TelemetryContext:
    raw = payload.get(TELEMETRY_PAYLOAD_KEY)
    if isinstance(raw, Mapping) and raw:
        return extract(raw)
    carrier: dict[str, str] = {}
    correlation = payload.get("correlation_id")
    if correlation is not None:
        carrier[CORRELATION_HEADER] = str(correlation)
    return extract(carrier)


def last_span_id_from_payload(payload: Mapping[str, object]) -> str | None:
    raw = payload.get(TELEMETRY_PAYLOAD_KEY)
    if not isinstance(raw, Mapping):
        return None
    value = raw.get(LAST_SPAN_ID_KEY)
    if isinstance(value, str) and value:
        return value
    return None


@contextmanager
def start_span(
    name: str,
    *,
    attributes: Mapping[str, object] | None = None,
    links: Sequence[tuple[str, str]] | None = None,
) -> Iterator[SpanRecord]:
    parent = _telemetry.get()
    if parent is None:
        child = _new_context(uuid4())
        parent_span_id = None
    else:
        child = TelemetryContext(
            trace_id=parent.trace_id,
            span_id=_new_span_id(),
            correlation_id=parent.correlation_id,
            trace_flags=parent.trace_flags,
            parent_span_id=parent.span_id,
        )
        parent_span_id = parent.span_id
    token = _telemetry.set(child)
    record = SpanRecord(
        name=name,
        trace_id=child.trace_id,
        span_id=child.span_id,
        parent_span_id=parent_span_id,
        correlation_id=child.correlation_id,
        attributes=span_attributes(attributes or {}),
        links=tuple(links or ()),
    )
    try:
        yield record
    finally:
        _ensure_runtime().exporter.emit(record)
        _telemetry.reset(token)


def sanitized_span_tree(spans: Sequence[SpanRecord]) -> list[dict[str, object]]:
    tree: list[dict[str, object]] = []
    for span in spans:
        tree.append(
            {
                "name": span.name,
                "trace_id": span.trace_id,
                "span_id": span.span_id,
                "parent_span_id": span.parent_span_id,
                "correlation_id": str(span.correlation_id),
                "attributes": {
                    key: redact(value) if isinstance(value, str) else value
                    for key, value in span.attributes.items()
                },
                "links": list(span.links),
            }
        )
    return tree
