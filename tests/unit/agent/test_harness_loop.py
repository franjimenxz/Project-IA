from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import UUID

import pytest

from ia_mcp.agent_runtime.context_compiler import ContextCompiler
from ia_mcp.agent_runtime.harness import AgentHarness
from ia_mcp.agent_runtime.models import (
    LLMDecision,
    LLMRequest,
    LLMTurnDecision,
    ToolCallProposal,
)
from ia_mcp.configuration.models import TenantConfig
from ia_mcp.contracts.common import ToolResult
from ia_mcp.contracts.errors import ToolError, ToolErrorCode
from ia_mcp.mcp.executor import ToolCall
from ia_mcp.skills.faq import SAFE_INSUFFICIENT
from ia_mcp.skills.registry import SkillRegistry
from ia_mcp.tenancy.models import TenantContext
from tests.unit.agent.test_harness import (
    TENANT_A,
    TENANT_B,
    FakeConfigRepository,
    FakeConversationRepository,
    FakeKnowledge,
    FakeRunRepository,
    config_for,
    hit,
    inbound,
    tenant_a,
)

SEARCH_ARGS: dict[str, object] = {
    "specialty": "cardiologia",
    "date_from": "2026-09-01",
    "date_to": "2026-09-01",
}
GET_ARGS: dict[str, object] = {"appointment_id": "apt-1"}
UPSTREAM_REF = "ref-not-a-secret"
ANSWER = LLMDecision(kind="answer", text="Hours are 8 to 16.", source_ids=("src-a",))
SEARCH_PROPOSAL = ToolCallProposal(name="appointments.search", arguments=SEARCH_ARGS)
GET_PROPOSAL = ToolCallProposal(name="appointments.get", arguments=GET_ARGS)


def tenant_b() -> TenantContext:
    return TenantContext(
        tenant_id=TENANT_B,
        tenant_slug="tenant-b",
        config_version=1,
        correlation_id=UUID("33333333-3333-3333-3333-333333333333"),
    )


class FakeClock:
    def __init__(self, value: float = 0.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value


class ScriptedLLM:
    def __init__(
        self,
        *steps: LLMTurnDecision | BaseException,
        clock: FakeClock | None = None,
        advance: float = 0.0,
    ) -> None:
        self._steps = list(steps)
        self.requests: list[LLMRequest] = []
        self._clock = clock
        self._advance = advance

    async def generate(self, request: LLMRequest) -> LLMTurnDecision:
        self.requests.append(request)
        if self._clock is not None:
            self._clock.value += self._advance
        step = self._steps.pop(0)
        if isinstance(step, BaseException):
            raise step
        return step


class RecordingExecutor:
    def __init__(self, result: ToolResult[Any] | None = None) -> None:
        self._result = result or ToolResult[dict[str, object]](
            ok=True, value={"slots": 2, "specialty": "cardiologia"}
        )
        self.calls: list[ToolCall] = []
        self.tenants: list[TenantContext] = []
        self.run_ids: list[UUID] = []

    async def execute(
        self,
        tenant: TenantContext,
        run_id: UUID,
        call: ToolCall,
        carrier: dict[str, str] | None = None,
    ) -> ToolResult[Any]:
        del carrier
        self.calls.append(call)
        self.tenants.append(tenant)
        self.run_ids.append(run_id)
        return self._result


class RecordingFactory:
    def __init__(self, executor: RecordingExecutor) -> None:
        self.executor = executor
        self.tenants: list[TenantContext] = []
        self.skills: list[str] = []
        self.configs: list[TenantConfig] = []

    async def for_tenant(
        self, tenant: TenantContext, config: TenantConfig, skill: str
    ) -> RecordingExecutor:
        self.tenants.append(tenant)
        self.configs.append(config)
        self.skills.append(skill)
        return self.executor


class PerTenantFactory:
    def __init__(self, executors: Mapping[UUID, RecordingExecutor]) -> None:
        self._executors = dict(executors)
        self.tenants: list[TenantContext] = []

    async def for_tenant(
        self, tenant: TenantContext, config: TenantConfig, skill: str
    ) -> RecordingExecutor:
        del config, skill
        self.tenants.append(tenant)
        return self._executors[tenant.tenant_id]


class LoopRunRepository(FakeRunRepository):
    def __init__(self) -> None:
        super().__init__()
        self.error_codes: list[str | None] = []

    async def finish(
        self,
        tenant: TenantContext,
        run_id: UUID,
        status: str,
        *,
        error_code: str | None = None,
        usage: dict[str, object] | None = None,
        error_detail: str | None = None,
    ) -> Any:
        self.error_codes.append(error_code)
        return await super().finish(
            tenant,
            run_id,
            status,
            error_code=error_code,
            usage=usage,
            error_detail=error_detail,
        )


def error_result(
    code: ToolErrorCode,
    safe_message: str,
    *,
    retryable: bool = False,
    upstream_reference: str | None = None,
) -> ToolResult[Any]:
    return ToolResult[Any](
        ok=False,
        error=ToolError(
            code=code,
            retryable=retryable,
            safe_message=safe_message,
            upstream_reference=upstream_reference,
        ),
    )


def make_loop_harness(
    *,
    llm: ScriptedLLM,
    executors: object | None = None,
    max_tool_iterations: int = 4,
    turn_deadline_seconds: float = 30.0,
    clock: FakeClock | None = None,
    knowledge: FakeKnowledge | None = None,
    runs: LoopRunRepository | None = None,
    configs: FakeConfigRepository | None = None,
) -> tuple[AgentHarness, FakeKnowledge, ScriptedLLM, LoopRunRepository]:
    configs = configs or FakeConfigRepository(
        {
            TENANT_A: config_for(TENANT_A, frozenset({"faq"})),
            TENANT_B: config_for(TENANT_B, frozenset({"faq"})),
        }
    )
    knowledge = knowledge or FakeKnowledge(hits=(hit(),))
    runs = runs or LoopRunRepository()
    compiler = ContextCompiler(
        configs=configs,
        skills=SkillRegistry(),
        tenant_tools={
            TENANT_A: frozenset({"appointments.search", "appointments.get"}),
            TENANT_B: frozenset({"appointments.search", "appointments.get"}),
        },
    )
    extra: dict[str, object] = {}
    if clock is not None:
        extra["clock"] = clock
    harness = AgentHarness(
        conversations=FakeConversationRepository(),
        runs=runs,
        configs=configs,
        skills=SkillRegistry(),
        compiler=compiler,
        knowledge=knowledge,
        llm=llm,
        executors=executors,
        max_tool_iterations=max_tool_iterations,
        turn_deadline_seconds=turn_deadline_seconds,
        **extra,
    )
    return harness, knowledge, llm, runs


@pytest.mark.anyio
async def test_tool_call_proposal_executes_and_triggers_second_generate() -> None:
    executor = RecordingExecutor()
    factory = RecordingFactory(executor)
    llm = ScriptedLLM(SEARCH_PROPOSAL, ANSWER)
    harness, _knowledge, _llm, runs = make_loop_harness(llm=llm, executors=factory)

    result = await harness.handle_message(tenant_a(), inbound("hours"))

    assert result.kind == "answer"
    assert result.source_ids == ("src-a",)
    assert len(llm.requests) == 2
    assert llm.requests[0].tool_results == ()
    assert len(llm.requests[1].tool_results) == 1
    observation = llm.requests[1].tool_results[0]
    assert observation.name == "appointments.search"
    assert observation.ok is True
    assert observation.value == {"slots": 2, "specialty": "cardiologia"}
    assert len(executor.calls) == 1
    assert executor.calls[0].name == "appointments.search"
    assert dict(executor.calls[0].arguments) == SEARCH_ARGS
    assert executor.tenants[0].tenant_id == TENANT_A
    assert executor.run_ids[0] == result.run_id
    assert factory.tenants[0].tenant_id == TENANT_A
    assert factory.skills == ["faq"]
    assert result.tool_calls
    assert result.tool_calls[0].name == "appointments.search"
    assert result.tool_calls[0].ok is True
    assert not hasattr(result.tool_calls[0], "arguments")
    assert runs.finished and runs.finished[0][1] == "succeeded"
    assert "generate" in result.trajectory


@pytest.mark.anyio
async def test_terminal_decision_calls_generate_exactly_once() -> None:
    executor = RecordingExecutor()
    llm = ScriptedLLM(ANSWER)
    harness, _knowledge, _llm, _runs = make_loop_harness(
        llm=llm, executors=RecordingFactory(executor)
    )

    result = await harness.handle_message(tenant_a(), inbound("hours"))

    assert result.kind == "answer"
    assert len(llm.requests) == 1
    assert executor.calls == []
    assert result.tool_calls == ()


@pytest.mark.anyio
async def test_max_tool_iterations_zero_does_not_execute() -> None:
    executor = RecordingExecutor()
    llm = ScriptedLLM(SEARCH_PROPOSAL, ANSWER)
    harness, _knowledge, _llm, _runs = make_loop_harness(
        llm=llm,
        executors=RecordingFactory(executor),
        max_tool_iterations=0,
    )

    result = await harness.handle_message(tenant_a(), inbound("hours"))

    assert len(llm.requests) == 1
    assert executor.calls == []
    assert result.tool_calls == ()


@pytest.mark.anyio
async def test_executors_none_does_not_execute() -> None:
    llm = ScriptedLLM(SEARCH_PROPOSAL, ANSWER)
    harness, _knowledge, _llm, _runs = make_loop_harness(
        llm=llm, executors=None, max_tool_iterations=4
    )

    result = await harness.handle_message(tenant_a(), inbound("hours"))

    assert len(llm.requests) == 1
    assert result.tool_calls == ()


@pytest.mark.anyio
async def test_budget_exhausted_is_insufficient_without_partial_answer() -> None:
    first = ToolCallProposal(
        name="appointments.search",
        arguments={**SEARCH_ARGS, "location": "one"},
    )
    second = ToolCallProposal(
        name="appointments.search",
        arguments={**SEARCH_ARGS, "location": "two"},
    )
    executor = RecordingExecutor()
    llm = ScriptedLLM(first, second, ANSWER)
    harness, _knowledge, _llm, runs = make_loop_harness(
        llm=llm,
        executors=RecordingFactory(executor),
        max_tool_iterations=1,
    )

    result = await harness.handle_message(tenant_a(), inbound("hours"))

    assert result.kind == "insufficient"
    assert result.text == SAFE_INSUFFICIENT
    assert "Hours are 8 to 16" not in result.text
    assert result.source_ids == ()
    assert len(executor.calls) == 1
    assert len(llm.requests) == 2
    assert runs.finished and runs.finished[0][1] == "failed"
    assert runs.error_codes == ["tool_budget_exhausted"]


@pytest.mark.anyio
async def test_deadline_exceeded_is_insufficient_without_partial_answer() -> None:
    clock = FakeClock()
    llm = ScriptedLLM(ANSWER, clock=clock, advance=31.0)
    executor = RecordingExecutor()
    harness, _knowledge, _llm, runs = make_loop_harness(
        llm=llm,
        executors=RecordingFactory(executor),
        turn_deadline_seconds=30.0,
        clock=clock,
    )

    result = await harness.handle_message(tenant_a(), inbound("hours"))

    assert result.kind == "insufficient"
    assert result.text == SAFE_INSUFFICIENT
    assert "Hours are 8 to 16" not in result.text
    assert result.source_ids == ()
    assert executor.calls == []
    assert runs.finished and runs.finished[0][1] == "failed"
    assert runs.error_codes == ["turn_deadline_exceeded"]
