from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

from ia_mcp.observability.redaction import redact

type HandoffReason = Literal[
    "explicit_request",
    "insufficient_knowledge",
    "persistent_error",
    "out_of_scope",
    "policy",
    "low_confidence",
    "manual_review_required",
]
type HandoffStatus = Literal["requested", "accepted", "resolved"]

HANDOFF_REASONS: frozenset[str] = frozenset(
    {
        "explicit_request",
        "insufficient_knowledge",
        "persistent_error",
        "out_of_scope",
        "policy",
        "low_confidence",
        "manual_review_required",
    }
)

_SENSITIVE_FRAGMENTS = (
    "password",
    "secret",
    "token",
    "credential",
    "authorization",
    "api_key",
)


def sanitize_fields(payload: Mapping[str, object] | None) -> dict[str, object]:
    if not payload:
        return {}
    cleaned: dict[str, object] = {}
    for key, value in payload.items():
        lowered = key.lower()
        if any(fragment in lowered for fragment in _SENSITIVE_FRAGMENTS):
            continue
        if isinstance(value, str):
            cleaned[key] = redact(value)
        else:
            cleaned[key] = value
    return cleaned


def sanitize_text(value: str | None) -> str | None:
    if value is None:
        return None
    return redact(value)


@dataclass(frozen=True, slots=True)
class HandoffRequest:
    conversation_id: UUID
    reason: HandoffReason
    business_key: str
    patient_reference: str | None = None
    collected_fields: Mapping[str, object] | None = None
    completed_actions: tuple[str, ...] = ()
    active_workflow_id: UUID | None = None
    notes: str | None = None


@dataclass(frozen=True, slots=True)
class HandoffSummary:
    patient_reference: str | None
    reason: HandoffReason
    collected_fields: Mapping[str, object]
    completed_actions: tuple[str, ...]
    active_workflow_id: UUID | None
    notes: str | None

    def as_payload(self) -> dict[str, object]:
        return {
            "patient_reference": self.patient_reference,
            "reason": self.reason,
            "collected_fields": dict(self.collected_fields),
            "completed_actions": list(self.completed_actions),
            "active_workflow_id": (
                str(self.active_workflow_id) if self.active_workflow_id else None
            ),
            "notes": self.notes,
        }


@dataclass(frozen=True, slots=True)
class HandoffCase:
    tenant_id: UUID
    id: UUID
    conversation_id: UUID
    workflow_id: UUID | None
    reason: HandoffReason
    summary: HandoffSummary
    business_key: str
    status: HandoffStatus
    external_case_reference: str | None
    owner_reference: str | None
    requested_at: datetime
    accepted_at: datetime | None
    resolved_at: datetime | None


@dataclass(frozen=True, slots=True)
class HandoffOutbox:
    tenant_id: UUID
    id: UUID
    kind: str
    payload: Mapping[str, object]
    created_at: datetime


@dataclass(frozen=True, slots=True)
class HandoffResult:
    handoff_id: UUID
    conversation_id: UUID
    tenant_id: UUID
    reason: HandoffReason
    status: HandoffStatus
    summary: HandoffSummary
    business_key: str
    replayed: bool
    delivery_pending: bool


@dataclass(frozen=True, slots=True)
class HandoffDelivery:
    handoff_id: UUID
    conversation_id: UUID
    reason: HandoffReason
    summary: HandoffSummary
    business_key: str
