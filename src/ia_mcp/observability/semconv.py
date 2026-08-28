from __future__ import annotations

from collections.abc import Mapping

from ia_mcp.observability.redaction import redact

SEMCONV_VERSION = "1.0.0"

CORRELATION_HEADER = "X-Correlation-ID"
TRACEPARENT_HEADER = "traceparent"
TELEMETRY_PAYLOAD_KEY = "telemetry"
LAST_SPAN_ID_KEY = "last_span_id"

SPAN_CHANNEL_RECEIVE = "channel.receive"
SPAN_CHANNEL_SEND = "channel.send"
SPAN_TENANT_RESOLVE = "tenant.resolve"
SPAN_CONVERSATION_LOAD = "conversation.load"
SPAN_AGENT_RUN = "agent.run"
SPAN_CONTEXT_COMPILE = "context.compile"
SPAN_KNOWLEDGE_SEARCH = "knowledge.search"
SPAN_LLM_GENERATE = "llm.generate"
SPAN_SKILL_ROUTE = "skill.route"
SPAN_WORKFLOW_ADVANCE = "workflow.advance"
SPAN_MCP_RESOLVE = "mcp.resolve"
SPAN_TOOL_EXECUTE = "tool.execute"
SPAN_HANDOFF_CREATE = "handoff.create"
SPAN_SCHEDULER_DISPATCH = "scheduler.dispatch"

ALLOWED_SPAN_ATTRIBUTES = frozenset(
    {
        "run_id",
        "tenant_id",
        "config_version",
        "skill",
        "workflow_type",
        "workflow_state",
        "tool_name",
        "mcp_server_id",
        "status",
        "error_code",
        "retry_count",
        "source_count",
        "token_count",
        "latency_ms",
        "job_id",
    }
)

ALLOWED_METRIC_LABELS = frozenset(
    {
        "tenant_id",
        "skill",
        "workflow_type",
        "tool_name",
        "status",
        "error_code",
        "mcp_server_id",
        "outcome",
    }
)

HIGH_CARDINALITY_METRIC_LABELS = frozenset(
    {
        "conversation_id",
        "run_id",
        "patient_id",
        "document_id",
        "message_id",
        "workflow_id",
        "job_id",
        "tool_execution_id",
    }
)

_FORBIDDEN_ATTRIBUTE_FRAGMENTS = (
    "content",
    "payload",
    "prompt",
    "completion",
    "body",
    "chunk",
    "authorization",
    "cookie",
    "secret",
    "password",
    "token",
    "credential",
    "api_key",
    "dni",
    "email",
    "phone",
    "telephone",
)


def span_attributes(raw: Mapping[str, object]) -> dict[str, object]:
    cleaned: dict[str, object] = {}
    for key, value in raw.items():
        if value is None:
            continue
        lowered = key.lower()
        if key not in ALLOWED_SPAN_ATTRIBUTES:
            continue
        if any(fragment == lowered for fragment in _FORBIDDEN_ATTRIBUTE_FRAGMENTS):
            continue
        if isinstance(value, str):
            cleaned[key] = redact(value)
        elif isinstance(value, bool | int | float):
            cleaned[key] = value
        else:
            cleaned[key] = redact(str(value))
    return cleaned


def metric_labels(**labels: str) -> dict[str, str]:
    return {
        key: value
        for key, value in labels.items()
        if key in ALLOWED_METRIC_LABELS and key not in HIGH_CARDINALITY_METRIC_LABELS
    }
