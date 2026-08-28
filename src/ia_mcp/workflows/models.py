from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

type WorkflowState = Literal[
    "collecting",
    "awaiting_confirmation",
    "executing",
    "completed",
    "failed",
    "manual_review_required",
    "cancelled",
]
type WorkflowStatus = Literal[
    "running",
    "completed",
    "failed",
    "cancelled",
    "manual_review_required",
]

_SENSITIVE_FRAGMENTS = (
    "password",
    "secret",
    "token",
    "credential",
    "authorization",
    "api_key",
)

_STATUS_BY_STATE: dict[WorkflowState, WorkflowStatus] = {
    "collecting": "running",
    "awaiting_confirmation": "running",
    "executing": "running",
    "completed": "completed",
    "failed": "failed",
    "cancelled": "cancelled",
    "manual_review_required": "manual_review_required",
}


def sanitize_payload(payload: Mapping[str, object] | None) -> dict[str, object]:
    if not payload:
        return {}
    cleaned: dict[str, object] = {}
    for key, value in payload.items():
        lowered = key.lower()
        if any(fragment in lowered for fragment in _SENSITIVE_FRAGMENTS):
            continue
        cleaned[key] = value
    return cleaned


def status_for(state: WorkflowState) -> WorkflowStatus:
    return _STATUS_BY_STATE[state]


@dataclass(frozen=True, slots=True)
class StartWorkflow:
    command_id: str
    workflow_type: str
    schema_version: int = 1
    conversation_id: UUID | None = None
    data: Mapping[str, object] | None = None
    actor: str = "system"
    run_id: UUID | None = None
    idempotency_key: str | None = None


@dataclass(frozen=True, slots=True)
class AdvanceCommand:
    workflow_id: UUID
    command_id: str
    event_type: str
    payload: Mapping[str, object] | None = None
    actor: str = "system"
    run_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class WorkflowExecution:
    tenant_id: UUID
    id: UUID
    conversation_id: UUID | None
    type: str
    schema_version: int
    state: WorkflowState
    status: WorkflowStatus
    data: Mapping[str, object]
    idempotency_key_hash: str | None
    lock_version: int
    created_at: datetime
    updated_at: datetime
    error: str | None


@dataclass(frozen=True, slots=True)
class WorkflowTransition:
    tenant_id: UUID
    workflow_id: UUID
    sequence: int
    from_state: WorkflowState | None
    to_state: WorkflowState
    command_id: str
    event_type: str
    payload: Mapping[str, object]
    actor: str
    run_id: UUID | None
    timestamp: datetime


@dataclass(frozen=True, slots=True)
class OutboxEvent:
    tenant_id: UUID
    id: UUID
    kind: str
    payload: Mapping[str, object]
    created_at: datetime


@dataclass(frozen=True, slots=True)
class WorkflowResult:
    workflow_id: UUID
    command_id: str
    type: str
    schema_version: int
    state: WorkflowState
    status: WorkflowStatus
    lock_version: int
    data: Mapping[str, object]
    error: str | None
