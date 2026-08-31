from __future__ import annotations

from dataclasses import asdict, fields
from uuid import UUID

from ia_mcp.agent_runtime.models import AgentTurnResult, ExecutedToolCall
from ia_mcp.agent_runtime.observations import observation_from
from ia_mcp.contracts.common import ToolResult
from ia_mcp.contracts.errors import ToolError, ToolErrorCode
from ia_mcp.evals.models import EvalCase
from ia_mcp.evals.runner import observe_turn
from ia_mcp.tenancy.models import TenantContext

TENANT_A = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
CORR = UUID("33333333-3333-3333-3333-333333333333")
UPSTREAM_REF = "ref-not-a-secret"


def _tenant() -> TenantContext:
    return TenantContext(
        tenant_id=TENANT_A,
        tenant_slug="tenant-a",
        config_version=1,
        correlation_id=CORR,
    )


def _eval_case() -> EvalCase:
    return EvalCase.model_validate(
        {
            "case_id": "uc-08-tenant-a-hours",
            "tenant_fixture": "tenant_a",
            "config_version": 1,
            "messages": [{"role": "user", "text": "cual es el horario?"}],
            "allowed_sources": ["kb-a-hours"],
            "forbidden_sources": ["kb-b-hours"],
            "expected_skill": "faq",
            "allowed_tools": ["appointments.search"],
            "forbidden_tools": ["appointments.create"],
            "expected_workflow_state": None,
            "expected_outcome": "answer",
            "assertions": [{"name": "grounded"}, {"name": "no_cross_tenant"}],
        }
    )


def _turn_result(
    *,
    tool_names: tuple[str, ...] = (),
    tool_calls: tuple[ExecutedToolCall, ...] = (),
) -> AgentTurnResult:
    return AgentTurnResult(
        kind="answer",
        text="Hours are 8 to 16.",
        source_ids=("kb-a-hours",),
        tenant_id=TENANT_A,
        run_id=None,
        trajectory=("receive",),
        tool_names=tool_names,
        tool_calls=tool_calls,
    )


def test_observation_from_ok_uses_sanitized_value() -> None:
    result = ToolResult[dict[str, object]](
        ok=True,
        value={"slots": 2, "specialty": "cardiologia"},
    )
    observation = observation_from("appointments.search", result)
    assert observation.name == "appointments.search"
    assert observation.ok is True
    assert observation.value == {"slots": 2, "specialty": "cardiologia"}
    assert observation.error_code is None
    assert observation.safe_message is None


def test_observation_from_error_copies_safe_fields_and_drops_upstream_reference() -> None:
    result = ToolResult[dict[str, object]](
        ok=False,
        error=ToolError(
            code=ToolErrorCode.UPSTREAM_UNAVAILABLE,
            retryable=True,
            safe_message="The service is unavailable.",
            upstream_reference=UPSTREAM_REF,
        ),
    )
    observation = observation_from("appointments.search", result)
    assert observation.name == "appointments.search"
    assert observation.ok is False
    assert observation.error_code == "upstream_unavailable"
    assert observation.safe_message == "The service is unavailable."
    assert observation.value is None
    assert not hasattr(observation, "upstream_reference")
    blob = " ".join(str(getattr(observation, item.name)) for item in fields(observation))
    blob = f"{blob} {observation!r} {asdict(observation)!s}"
    assert UPSTREAM_REF not in blob
    assert "upstream_reference" not in blob


def test_observation_from_strips_token_and_secret_keys() -> None:
    result = ToolResult[dict[str, object]](
        ok=True,
        value={
            "specialty": "cardiologia",
            "token": "placeholder-not-a-credential",
            "secret": "placeholder-not-a-credential",
        },
    )
    observation = observation_from("appointments.search", result)
    assert observation.ok is True
    assert observation.value == {"specialty": "cardiologia"}
    assert observation.value is not None
    assert "token" not in observation.value
    assert "secret" not in observation.value


def test_observe_turn_empty_tool_calls_reports_announced_tool_names() -> None:
    result = _turn_result(tool_names=("appointments.search",), tool_calls=())
    observed = observe_turn(_eval_case(), _tenant(), result)
    assert tuple(call.name for call in observed.tool_calls) == ("appointments.search",)
    assert observed.tool_calls[0].arguments == {}


def test_observe_turn_nonempty_tool_calls_reports_executed_names_not_announced() -> None:
    result = _turn_result(
        tool_names=("appointments.search", "appointments.get"),
        tool_calls=(ExecutedToolCall(name="appointments.search", ok=True),),
    )
    observed = observe_turn(_eval_case(), _tenant(), result)
    names = tuple(call.name for call in observed.tool_calls)
    assert names == ("appointments.search",)
    assert "appointments.get" not in names
    assert observed.tool_calls[0].arguments == {}
