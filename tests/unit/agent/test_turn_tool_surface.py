from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest

from ia_mcp.agent_runtime.context_compiler import ContextCompiler
from ia_mcp.agent_runtime.harness import AgentHarness, invocable_on_turn
from ia_mcp.agent_runtime.models import LLMDecision, ToolCallProposal
from ia_mcp.configuration.models import AgentConfig, TenantConfig
from ia_mcp.contracts.common import ToolResult
from ia_mcp.mcp.executor import McpTarget, ToolCall
from ia_mcp.skills.registry import SkillRegistry
from ia_mcp.tenancy.models import TenantContext
from tests.unit.agent.test_harness import (
    TENANT_A,
    FakeConfigRepository,
    FakeConversationRepository,
    FakeKnowledge,
    FakeRunRepository,
    hit,
    inbound,
    tenant_a,
)
from tests.unit.agent.test_harness_loop import (
    ANSWER,
    GET_PROPOSAL,
    SEARCH_PROPOSAL,
    RecordingExecutor,
    RecordingFactory,
    ScriptedLLM,
    make_loop_harness,
    tenant_b,
)
from tests.unit.mcp.test_executor import CapabilitySpy, TransportSpy

MUTATING_CANONICAL = (
    "appointments.create",
    "appointments.cancel",
    "appointments.reschedule",
    "appointments.confirm",
)
NON_CANONICAL = "crear_turno"


def _faq_config(*tools: str) -> TenantConfig:
    return TenantConfig(
        tenant_id=TENANT_A,
        version=1,
        agent=AgentConfig(tone="cordial"),
        enabled_skills=frozenset({"faq"}),
        enabled_tools=frozenset(tools),
    )


def test_invocable_on_turn_honors_declared_names() -> None:
    declared = frozenset({"appointments.create", NON_CANONICAL})
    assert invocable_on_turn("appointments.create", declared_for_turn=declared)
    assert invocable_on_turn(NON_CANONICAL, declared_for_turn=declared)
    assert invocable_on_turn("appointments.create") is False
    assert invocable_on_turn("appointments.search") is True
    assert invocable_on_turn(NON_CANONICAL) is False


class AnyFactory:
    def __init__(self, executor: object) -> None:
        self.executor = executor
        self.tenants: list[TenantContext] = []

    async def for_tenant(
        self, tenant: TenantContext, config: TenantConfig, skill: str
    ) -> object:
        del config, skill
        self.tenants.append(tenant)
        return self.executor


class CapabilityExecutor:
    """Calls the capability if the harness invokes execute."""

    def __init__(self, capability: CapabilitySpy) -> None:
        self.capability = capability
        self.calls: list[ToolCall] = []

    async def execute(
        self,
        tenant: TenantContext,
        run_id: UUID,
        call: ToolCall,
        carrier: dict[str, str] | None = None,
    ) -> ToolResult[Any]:
        del tenant, run_id, carrier
        self.calls.append(call)
        method = getattr(self.capability, call.name.rsplit(".", 1)[-1])
        returned = await method()
        if isinstance(returned, ToolResult):
            return returned
        return ToolResult[dict[str, object]](ok=True, value={"dispatched": call.name})


class TransportExecutor:
    """Calls generic transport if the harness invokes execute."""

    def __init__(self, transport: TransportSpy) -> None:
        self.transport = transport
        self.calls: list[ToolCall] = []

    async def execute(
        self,
        tenant: TenantContext,
        run_id: UUID,
        call: ToolCall,
        carrier: dict[str, str] | None = None,
    ) -> ToolResult[Any]:
        del run_id, carrier
        self.calls.append(call)
        return await self.transport.call_tool(
            tenant,
            McpTarget(server_id="mcp-b", allowed_tools=frozenset({call.name})),
            call.name,
            dict(call.arguments),
        )


class PerTenantFactory:
    def __init__(self, mapping: dict[UUID, RecordingExecutor]) -> None:
        self._mapping = mapping
        self.seen: list[UUID] = []

    async def for_tenant(
        self, tenant: TenantContext, config: TenantConfig, skill: str
    ) -> RecordingExecutor:
        del config, skill
        self.seen.append(tenant.tenant_id)
        return self._mapping[tenant.tenant_id]


@pytest.mark.anyio
@pytest.mark.parametrize("name", MUTATING_CANONICAL)
async def test_mutating_canonical_is_forbidden_without_capability(name: str) -> None:
    capability = CapabilitySpy()
    executor = CapabilityExecutor(capability)
    llm = ScriptedLLM(
        ToolCallProposal(name=name, arguments={"appointment_id": "apt-1"}),
        ANSWER,
    )
    harness, _knowledge, _llm, _runs = make_loop_harness(
        llm=llm, executors=AnyFactory(executor)
    )

    result = await harness.handle_message(tenant_a(), inbound("book"))

    assert executor.calls == []
    capability.assert_not_called()
    assert result.tool_calls
    assert result.tool_calls[0].name == name
    assert result.tool_calls[0].ok is False
    assert result.tool_calls[0].error_code == "forbidden"
    assert llm.requests[1].tool_results[0].error_code == "forbidden"
    assert llm.requests[1].tool_results[0].ok is False


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("proposal", "method"),
    ((SEARCH_PROPOSAL, "search"), (GET_PROPOSAL, "get")),
)
async def test_search_and_get_are_invocable_when_in_the_intersection(
    proposal: ToolCallProposal, method: str
) -> None:
    capability = CapabilitySpy()
    getattr(capability, method).return_value = ToolResult[dict[str, object]](
        ok=True, value={"id": "apt-1"}
    )
    executor = CapabilityExecutor(capability)
    llm = ScriptedLLM(proposal, ANSWER)
    harness, _knowledge, _llm, _runs = make_loop_harness(
        llm=llm, executors=AnyFactory(executor)
    )

    result = await harness.handle_message(tenant_a(), inbound("hours"))

    assert len(executor.calls) == 1
    assert executor.calls[0].name == proposal.name
    assert result.tool_calls[0].ok is True
    assert result.tool_calls[0].name == proposal.name
    getattr(capability, method).assert_awaited()


@pytest.mark.anyio
async def test_undeclared_non_canonical_is_forbidden_without_transport() -> None:
    transport = TransportSpy()
    executor = TransportExecutor(transport)
    llm = ScriptedLLM(
        ToolCallProposal(name=NON_CANONICAL, arguments={"slot": "manana"}),
        ANSWER,
    )
    harness, _knowledge, _llm, _runs = make_loop_harness(
        llm=llm, executors=AnyFactory(executor)
    )

    result = await harness.handle_message(tenant_a(), inbound("book"))

    assert executor.calls == []
    transport.assert_not_called()
    assert result.tool_calls[0].ok is False
    assert result.tool_calls[0].error_code == "forbidden"
    assert result.tool_calls[0].name == NON_CANONICAL


@pytest.mark.anyio
async def test_tenant_a_cannot_execute_tool_discovered_only_on_tenant_b() -> None:
    from ia_mcp.contracts.errors import ToolError, ToolErrorCode

    executor_a = RecordingExecutor(
        ToolResult[Any](
            ok=False,
            error=ToolError(
                code=ToolErrorCode.FORBIDDEN,
                retryable=False,
                safe_message="Action is not allowed.",
            ),
        )
    )
    executor_b = RecordingExecutor()
    factory = PerTenantFactory({TENANT_A: executor_a, tenant_b().tenant_id: executor_b})
    llm = ScriptedLLM(SEARCH_PROPOSAL, ANSWER)
    harness, _knowledge, _llm, _runs = make_loop_harness(llm=llm, executors=factory)

    result = await harness.handle_message(tenant_a(), inbound("hours"))

    assert factory.seen == [TENANT_A]
    assert executor_b.calls == []
    assert [call.name for call in executor_a.calls] == ["appointments.search"]
    assert executor_a.tenants[0].tenant_id == TENANT_A
    assert result.tenant_id == TENANT_A
    assert all(request.tenant_id == TENANT_A for request in llm.requests)


@pytest.mark.anyio
async def test_tenant_b_turn_uses_tenant_b_executor_not_tenant_a() -> None:
    executor_a = RecordingExecutor()
    executor_b = RecordingExecutor()
    factory = PerTenantFactory({TENANT_A: executor_a, tenant_b().tenant_id: executor_b})
    llm = ScriptedLLM(SEARCH_PROPOSAL, ANSWER)
    harness, _knowledge, _llm, _runs = make_loop_harness(llm=llm, executors=factory)

    result = await harness.handle_message(tenant_b(), inbound("hours"))

    assert factory.seen == [tenant_b().tenant_id]
    assert executor_a.calls == []
    assert executor_b.calls
    assert executor_b.tenants[0].tenant_id == tenant_b().tenant_id
    assert result.tenant_id == tenant_b().tenant_id
    assert all(request.tenant_id == tenant_b().tenant_id for request in llm.requests)


def _announced_harness(
    *,
    llm: ScriptedLLM,
    executor: object,
    tools: frozenset[str],
    knowledge: FakeKnowledge | None = None,
) -> AgentHarness:
    configs = FakeConfigRepository({TENANT_A: _faq_config(*tools)})
    compiler = ContextCompiler(
        configs=configs,
        skills=SkillRegistry(),
        tenant_tools={},
        server_tools=tools,
    )
    return AgentHarness(
        conversations=FakeConversationRepository(),
        runs=FakeRunRepository(),
        configs=configs,
        skills=SkillRegistry(),
        compiler=compiler,
        knowledge=knowledge or FakeKnowledge(hits=(hit(),)),
        llm=llm,
        executors=AnyFactory(executor),
    )


@pytest.mark.anyio
@pytest.mark.parametrize("name", ("appointments.create", NON_CANONICAL))
async def test_announced_mutation_reaches_executor(name: str) -> None:
    executor = RecordingExecutor()
    llm = ScriptedLLM(ToolCallProposal(name=name, arguments={"slot": "manana"}), ANSWER)
    harness = _announced_harness(llm=llm, executor=executor, tools=frozenset({name}))

    result = await harness.handle_message(tenant_a(), inbound("book"))

    assert [call.name for call in executor.calls] == [name]
    assert result.tool_calls[0].name == name
    assert result.tool_calls[0].ok is True
    assert llm.requests[0].tool_names == (name,)


@pytest.mark.anyio
async def test_empty_knowledge_with_enabled_tools_reaches_llm() -> None:
    llm = ScriptedLLM(ANSWER)
    configs = FakeConfigRepository({TENANT_A: _faq_config("appointments.search")})
    harness, _knowledge, _llm, _runs = make_loop_harness(
        llm=llm,
        knowledge=FakeKnowledge(hits=()),
        configs=configs,
    )

    result = await harness.handle_message(tenant_a(), inbound("hours"))

    assert llm.requests
    assert "generate" in result.trajectory


@pytest.mark.anyio
async def test_answer_after_successful_tool_does_not_require_cites() -> None:
    executor = RecordingExecutor()
    llm = ScriptedLLM(
        SEARCH_PROPOSAL,
        LLMDecision(kind="answer", text="Hay turnos el martes.", source_ids=()),
    )
    configs = FakeConfigRepository({TENANT_A: _faq_config("appointments.search")})
    harness, _knowledge, _llm, _runs = make_loop_harness(
        llm=llm,
        executors=RecordingFactory(executor),
        knowledge=FakeKnowledge(hits=()),
        configs=configs,
    )

    result = await harness.handle_message(tenant_a(), inbound("book"))

    assert executor.calls
    assert result.kind == "answer"
    assert result.text == "Hay turnos el martes."
    assert result.source_ids == ()
