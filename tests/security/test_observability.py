"""AC-P07-008: metric cardinality, span sanitization, inbound trust."""

from __future__ import annotations

from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from ia_mcp.api.app import create_app
from ia_mcp.observability.context import CORRELATION_HEADER
from ia_mcp.observability.propagation import (
    TRACEPARENT_HEADER,
    configure_telemetry,
    extract,
    flush_telemetry,
    recorded_spans,
    reset_telemetry_context,
    sanitized_span_tree,
    start_span,
)
from ia_mcp.observability.semconv import (
    SPAN_TOOL_EXECUTE,
    metric_labels,
    span_attributes,
)


def test_metric_labels_drop_high_cardinality_ids() -> None:
    labels = metric_labels(
        conversation_id=str(uuid4()),
        run_id=str(uuid4()),
        patient_id="pat-1",
        document_id="doc-1",
        message_id=str(uuid4()),
        skill="faq",
        status="ok",
        tenant_id="tenant-a",
    )
    assert "conversation_id" not in labels
    assert "run_id" not in labels
    assert "patient_id" not in labels
    assert "document_id" not in labels
    assert "message_id" not in labels
    assert labels["skill"] == "faq"
    assert labels["status"] == "ok"
    assert labels["tenant_id"] == "tenant-a"


def test_spans_omit_content_payload_and_secrets() -> None:
    configure_telemetry()
    reset_telemetry_context()
    with start_span(
        SPAN_TOOL_EXECUTE,
        attributes={
            "prompt": "Answer using Bearer secret-token",
            "payload": {"authorization": "Bearer secret-token"},
            "content": "patient@example.com DNI 30111222",
            "completion": "full model output",
            "tool_name": "appointments.search",
            "status": "ok",
            "error_detail": "Bearer secret-token for patient@example.com",
        },
    ) as span:
        span.set_attribute(
            "status",
            "Basic dXNlcjpwYXNz api_key=sk-live-secret +54 11 4444-5555",
        )
        span.set_attribute("prompt", "should-not-land")
    flush_telemetry()
    spans = recorded_spans()
    assert len(spans) == 1
    attrs = spans[0].attributes
    assert "prompt" not in attrs
    assert "payload" not in attrs
    assert "content" not in attrs
    assert "completion" not in attrs
    assert attrs["tool_name"] == "appointments.search"
    dumped = str(sanitized_span_tree(spans))
    assert "secret-token" not in dumped
    assert "patient@example.com" not in dumped
    assert "30111222" not in dumped
    assert "dXNlcjpwYXNz" not in dumped
    assert "sk-live-secret" not in dumped
    assert "4444-5555" not in dumped
    assert "Bearer" not in dumped or "[REDACTED]" in dumped
    sanitized = span_attributes(
        {
            "authorization": "Bearer secret-token",
            "tool_name": "appointments.search",
        }
    )
    assert "authorization" not in sanitized
    assert sanitized["tool_name"] == "appointments.search"


def test_unauthenticated_request_ignores_foreign_correlation() -> None:
    """Inbound traceparent/correlation are not trusted at the public HTTP boundary."""
    configure_telemetry()
    tenant_b = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
    foreign_trace = "00-" + ("b" * 32) + "-" + ("c" * 16) + "-01"
    client = TestClient(create_app())
    response = client.get(
        "/health/live",
        headers={
            CORRELATION_HEADER: str(tenant_b),
            TRACEPARENT_HEADER: foreign_trace,
        },
    )
    assert response.status_code == 200
    returned = UUID(response.headers[CORRELATION_HEADER])
    assert returned != tenant_b
    ctx = extract(response.headers)
    assert ctx.correlation_id != tenant_b
    assert ctx.trace_id != "b" * 32
    assert "b" * 32 not in response.headers[TRACEPARENT_HEADER]
