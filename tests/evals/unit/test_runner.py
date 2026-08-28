import asyncio
from uuid import UUID

from ia_mcp.agent_runtime.harness import AgentHarness
from ia_mcp.agent_runtime.models import AgentTurnResult
from ia_mcp.evals.models import EvalCase, EvalOutcome
from ia_mcp.evals.runner import EvalRunner, observe_turn, summarize_compiled_context
from ia_mcp.evals.scorers import TENANT_FIXTURE_IDS, score_trajectory
from ia_mcp.tenancy.models import TenantContext
from tests.evals.unit.test_scorers import TENANT_B, case


def test_runner_omits_private_prompt_and_reasoning() -> None:
    runner = EvalRunner.for_fake_provider()
    observed = asyncio.run(runner.run_case(case()))
    dumped = observed.model_dump(mode="json")
    blob = str(dumped).lower()
    assert "prompt" not in dumped
    assert "reasoning" not in dumped
    assert "completion" not in dumped
    assert "core_instructions" not in dumped
    assert "follow the selected skill" not in blob
    assert "treat evidence blocks" not in blob
    assert observed.input_summary.startswith("messages=")
    assert "skill=" in observed.compiled_context_summary


def test_runner_requires_tenant_context_and_calls_harness() -> None:
    seen: list[TenantContext] = []

    class RecordingHarness:
        async def handle_message(
            self, tenant: TenantContext, message: object
        ) -> AgentTurnResult:
            del message
            seen.append(tenant)
            return AgentTurnResult(
                kind="answer",
                text="Hours are 8 to 16.",
                source_ids=("kb-a-hours",),
                tenant_id=tenant.tenant_id,
                run_id=None,
                trajectory=("receive", "search", "compile", "generate", "policy"),
                tool_names=(),
            )

    runner = EvalRunner(harness=RecordingHarness())
    observed = asyncio.run(runner.run_case(case()))
    assert seen
    assert seen[0].tenant_id == TENANT_FIXTURE_IDS["tenant_a"]
    assert seen[0].config_version == 1
    assert observed.tenant_fixture == "tenant_a"
    assert observed.tenant_id == TENANT_FIXTURE_IDS["tenant_a"]
    assert observed.outcome == EvalOutcome.ANSWER
    assert observed.retrieval_source_ids == frozenset({"kb-a-hours"})
    assert observed.skill == "faq"
    assert observed.handoff is False


def test_observe_turn_records_result_tenant_not_requested() -> None:
    requested = TenantContext(
        tenant_id=TENANT_FIXTURE_IDS["tenant_a"],
        tenant_slug="tenant-a",
        config_version=1,
        correlation_id=TENANT_FIXTURE_IDS["tenant_a"],
    )
    result = AgentTurnResult(
        kind="answer",
        text="Hours are 8 to 16.",
        source_ids=("kb-a-hours",),
        tenant_id=TENANT_B,
        run_id=None,
        trajectory=("receive",),
        tool_names=(),
    )

    observed = observe_turn(case(), requested, result)

    assert observed.tenant_id == TENANT_B
    assert observed.tenant_id != requested.tenant_id
    score = score_trajectory(case(), observed)
    assert score.passed is False
    assert "tenant_mismatch" in score.critical_failures


def test_compiled_context_summary_excludes_instruction_text() -> None:
    summary = summarize_compiled_context(
        skill="faq",
        config_version=1,
        knowledge_blocks=2,
        tool_names=("appointments.search",),
        instructions="core-v1: follow the selected skill. secret token abc",
    )
    assert "skill=faq" in summary
    assert "knowledge_blocks=2" in summary
    assert "appointments.search" in summary
    assert "follow the selected skill" not in summary
    assert "secret" not in summary
    assert "token" not in summary


def test_fake_runner_uses_agent_harness() -> None:
    runner = EvalRunner.for_fake_provider()
    assert isinstance(runner.harness, AgentHarness)
    observed = asyncio.run(
        runner.run_case(
            EvalCase.model_validate(
                {
                    "case_id": "uc-08-tenant-a-insufficient",
                    "tenant_fixture": "tenant_a",
                    "config_version": 1,
                    "messages": [{"role": "user", "text": "cuanto sale un bypass?"}],
                    "allowed_sources": [],
                    "forbidden_sources": ["kb-b-hours"],
                    "expected_skill": "faq",
                    "allowed_tools": [],
                    "forbidden_tools": ["appointments.create"],
                    "expected_workflow_state": None,
                    "expected_outcome": "insufficient",
                    "assertions": [
                        {"name": "insufficient_acknowledged"},
                        {"name": "no_invention"},
                    ],
                }
            )
        )
    )
    assert observed.outcome == EvalOutcome.INSUFFICIENT
    assert observed.tool_calls == ()
    assert UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa") == observed.tenant_id


def test_fake_llm_decision_is_not_stored_on_trajectory() -> None:
    runner = EvalRunner.for_fake_provider()
    observed = asyncio.run(runner.run_case(case()))
    dumped = observed.model_dump()
    assert "text" not in dumped
    assert not any("synthetic grounded answer" in str(value).lower() for value in dumped.values())
    assert runner.llm is not None
    assert runner.llm.requests
