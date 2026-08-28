from enum import StrEnum
from re import fullmatch
from typing import Literal

from pydantic import BaseModel, ConfigDict, PositiveInt, field_validator

from ia_mcp.configuration.models import SkillName
from ia_mcp.contracts.common import NonEmptyStr
from ia_mcp.workflows.models import WorkflowState

CASE_ID_PATTERN = r"^uc-(0[1-9]|10)-tenant-[ab]-[a-z0-9-]+$"
ADVERSARIAL_TAGS: tuple[str, ...] = (
    "insufficient",
    "injection",
    "tool-forbidden",
    "timeout",
    "handoff",
)


class EvalOutcome(StrEnum):
    ANSWER = "answer"
    CLARIFY = "clarify"
    INSUFFICIENT = "insufficient"
    HANDOFF = "handoff"
    COMPLETED = "completed"
    MANUAL_REVIEW_REQUIRED = "manual_review_required"
    FAILED = "failed"


class EvalMessage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    role: Literal["user", "assistant"]
    text: NonEmptyStr


class SemanticAssertion(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: Literal[
        "grounded",
        "no_invention",
        "no_cross_tenant",
        "no_forbidden_tool",
        "no_forbidden_source",
        "injection_ignored",
        "handoff_structured",
        "timeout_no_invented_success",
        "insufficient_acknowledged",
        "reminder_dispatched",
        "reminder_skipped",
        "reminder_deduped",
    ]


class EvalCase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: NonEmptyStr
    tenant_fixture: Literal["tenant_a", "tenant_b"]
    config_version: PositiveInt
    messages: tuple[EvalMessage, ...]
    allowed_sources: frozenset[str]
    forbidden_sources: frozenset[str]
    expected_skill: SkillName
    allowed_tools: frozenset[str]
    forbidden_tools: frozenset[str]
    expected_workflow_state: WorkflowState | None
    expected_outcome: EvalOutcome
    assertions: tuple[SemanticAssertion, ...]

    @field_validator("case_id")
    @classmethod
    def case_id_has_stable_pattern(cls, value: str) -> str:
        if fullmatch(CASE_ID_PATTERN, value) is None:
            raise ValueError("case_id must match uc-NN-tenant-[ab]-<slug>")
        return value

    @field_validator("messages")
    @classmethod
    def messages_are_present(cls, value: tuple[EvalMessage, ...]) -> tuple[EvalMessage, ...]:
        if not value:
            raise ValueError("messages must not be empty")
        return value


class DatasetValidationReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    valid: bool
    case_count: int
    dataset_hash: str
    issues: tuple[str, ...]
    use_case_counts: dict[str, int]
    tenant_counts: dict[str, int]
    adversarial_counts: dict[str, int]
