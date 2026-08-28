from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import AnyUrl, BaseModel, ConfigDict, Field

type TimelineKind = Literal[
    "run_started",
    "run_finished",
    "transition",
    "retry",
    "job",
    "tool",
    "handoff",
    "retrieval",
]


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RunSummary(_Frozen):
    id: UUID
    conversation_id: UUID
    config_version: int
    skill: str | None
    workflow_type: str | None
    mcp_server_id: str | None
    status: str
    error_code: str | None
    model_provider: str | None
    model_name: str | None
    started_at: datetime
    finished_at: datetime | None
    latency_ms: int | None
    input_tokens: int | None
    output_tokens: int | None
    correlation_id: UUID


class ConversationSummary(_Frozen):
    id: UUID
    status: str
    last_message_at: datetime
    trigger_message_id: UUID
    trigger_direction: str
    trigger_content_type: str


class RetrievalSummary(_Frozen):
    source_id: str
    occurred_at: datetime


class WorkflowSummary(_Frozen):
    id: UUID
    type: str
    state: str
    status: str
    error: str | None
    schema_version: int


class ToolExecutionSummary(_Frozen):
    tool_name: str
    mcp_server_id: str | None
    status: str
    error_code: str | None
    occurred_at: datetime
    retry_count: int = 0
    sequence: int


class HandoffSummary(_Frozen):
    id: UUID
    status: str
    reason: str
    requested_at: datetime
    accepted_at: datetime | None
    resolved_at: datetime | None


class JobSummary(_Frozen):
    id: UUID
    type: str
    status: str
    attempts: int
    scheduled_for: datetime
    created_at: datetime
    last_error: str | None


class AuditEventSummary(_Frozen):
    id: UUID
    action: str
    created_at: datetime
    version: int | None


class TimelineEvent(_Frozen):
    occurred_at: datetime
    kind: TimelineKind
    label: str
    ref: str
    error_code: str | None = None


class RunInvestigation(_Frozen):
    run: RunSummary
    conversation: ConversationSummary
    retrievals: tuple[RetrievalSummary, ...]
    workflow: WorkflowSummary | None
    tools: tuple[ToolExecutionSummary, ...]
    handoff: HandoffSummary | None
    jobs: tuple[JobSummary, ...]
    audit_events: tuple[AuditEventSummary, ...]
    trace_url: AnyUrl | None = None
    timeline: tuple[TimelineEvent, ...] = Field(default_factory=tuple)
    tools_next_cursor: str | None = None
    audit_next_cursor: str | None = None
