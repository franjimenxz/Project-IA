from uuid import UUID

from ia_mcp.evals.models import EvalCase, EvalOutcome, SemanticAssertion
from ia_mcp.evals.scorers import ObservedToolCall, ObservedTrajectory, score_trajectory

TENANT_A = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
TENANT_B = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")


def case(**overrides: object) -> EvalCase:
    payload: dict[str, object] = {
        "case_id": "uc-08-tenant-a-hours",
        "tenant_fixture": "tenant_a",
        "config_version": 1,
        "messages": [{"role": "user", "text": "cual es el horario?"}],
        "allowed_sources": ["kb-a-hours"],
        "forbidden_sources": ["kb-b-hours"],
        "expected_skill": "faq",
        "allowed_tools": [],
        "forbidden_tools": ["appointments.create"],
        "expected_workflow_state": None,
        "expected_outcome": "answer",
        "assertions": [{"name": "grounded"}, {"name": "no_cross_tenant"}],
    }
    payload.update(overrides)
    return EvalCase.model_validate(payload)


def observed(**overrides: object) -> ObservedTrajectory:
    tools = overrides.pop("tools", None)
    if tools is None:
        tool_calls = overrides.pop("tool_calls", ())
    else:
        names = tools if isinstance(tools, (set, frozenset, list, tuple)) else (tools,)
        tool_calls = tuple(ObservedToolCall(name=str(name)) for name in names)
    payload: dict[str, object] = {
        "case_id": "uc-08-tenant-a-hours",
        "tenant_fixture": "tenant_a",
        "tenant_id": TENANT_A,
        "config_version": 1,
        "input_summary": "messages=1 roles=user",
        "compiled_context_summary": "skill=faq knowledge_blocks=1 tools=none",
        "retrieval_source_ids": frozenset({"kb-a-hours"}),
        "skill": "faq",
        "tool_calls": tool_calls,
        "workflow_state": None,
        "workflow_transitions": (),
        "handoff": False,
        "outcome": EvalOutcome.ANSWER,
    }
    payload.update(overrides)
    return ObservedTrajectory.model_validate(payload)


def test_forbidden_tool_fails_critical_case() -> None:
    score = score_trajectory(
        case(forbidden_tools={"patients.get"}),
        observed(tools={"patients.get"}),
    )
    assert score.passed is False
    assert score.critical_failures == ("forbidden_tool:patients.get",)


def test_forbidden_source_is_deterministic_critical_failure() -> None:
    score = score_trajectory(
        case(),
        observed(retrieval_source_ids=frozenset({"kb-a-hours", "kb-b-hours"})),
    )
    assert score.passed is False
    assert "forbidden_source:kb-b-hours" in score.critical_failures


def test_tenant_mismatch_is_exact_critical_failure() -> None:
    score = score_trajectory(
        case(),
        observed(tenant_fixture="tenant_b", tenant_id=TENANT_B),
    )
    assert score.passed is False
    assert "tenant_mismatch" in score.critical_failures


def test_matching_trajectory_passes_without_judge() -> None:
    score = score_trajectory(case(), observed())
    assert score.passed is True
    assert score.critical_failures == ()


def test_critical_case_failure_overrides_high_average() -> None:
    passing = [
        score_trajectory(case(), observed())
        for _ in range(9)
    ]
    critical = score_trajectory(
        case(
            forbidden_tools={"appointments.create"},
            assertions=[
                SemanticAssertion(name="no_forbidden_tool"),
                SemanticAssertion(name="no_cross_tenant"),
            ],
        ),
        observed(tools={"appointments.create"}),
    )
    scores = [*passing, critical]
    averages = {
        "skill": sum(item.category_scores["skill"] for item in scores) / len(scores),
        "groundedness": sum(item.category_scores["groundedness"] for item in scores)
        / len(scores),
    }
    assert averages["skill"] >= 0.9
    assert averages["groundedness"] >= 0.9
    assert critical.passed is False
    assert any(item.critical and not item.passed for item in scores)
