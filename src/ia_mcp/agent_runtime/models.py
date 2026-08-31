from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

type AnswerKind = Literal["answer", "clarify", "insufficient", "handoff"]


@dataclass(frozen=True, slots=True)
class ToolCallProposal:
    name: str
    arguments: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class ToolObservation:
    name: str
    ok: bool
    value: Mapping[str, object] | None = None
    error_code: str | None = None
    safe_message: str | None = None


@dataclass(frozen=True, slots=True)
class ExecutedToolCall:
    name: str
    ok: bool
    error_code: str | None = None


@dataclass(frozen=True, slots=True)
class LLMRequest:
    tenant_id: UUID
    skill: str
    query: str
    instructions: str
    knowledge: tuple[str, ...]
    history: tuple[str, ...]
    allowed_source_ids: tuple[str, ...]
    tool_names: tuple[str, ...] = ()
    tool_results: tuple[ToolObservation, ...] = ()
    tone: str = ""
    tenant_instructions: str | None = None


@dataclass(frozen=True, slots=True)
class LLMDecision:
    kind: AnswerKind
    text: str
    source_ids: tuple[str, ...]


type LLMTurnDecision = LLMDecision | ToolCallProposal


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    kind: AnswerKind
    text: str
    source_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AgentTurnResult:
    kind: AnswerKind
    text: str
    source_ids: tuple[str, ...]
    tenant_id: UUID
    run_id: UUID | None
    trajectory: tuple[str, ...]
    tool_names: tuple[str, ...] = ()
    tool_calls: tuple[ExecutedToolCall, ...] = ()
