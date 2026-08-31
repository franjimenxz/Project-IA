"""AC-P11-010: the conversational tool loop stays inside the turn tenant."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any
from uuid import UUID

import pytest

from ia_mcp.configuration.models import AgentConfig, TenantConfig
from ia_mcp.contracts.common import ToolResult
from ia_mcp.contracts.errors import ToolErrorCode
from ia_mcp.mcp.executor import McpTarget, ToolAuditEvent, ToolCall, ToolExecutor
from ia_mcp.skills.faq import SAFE_INSUFFICIENT
from ia_mcp.tenancy.models import TenantContext
from tests.unit.agent.test_harness import (
    TENANT_A,
    TENANT_B,
    FakeConfigRepository,
    config_for,
    inbound,
    tenant_a,
)
from tests.unit.agent.test_harness_loop import (
    ANSWER,
    GET_PROPOSAL,
    SEARCH_PROPOSAL,
    PerTenantFactory,
    RecordingExecutor,
    RecordingFactory,
    ScriptedLLM,
    error_result,
    make_loop_harness,
    tenant_b,
)
from tests.unit.mcp.test_executor import CapabilitySpy, TransportSpy

pytestmark = [pytest.mark.security]

B_ONLY_DISCOVERED = "appointments.get"
READ_SURFACE = frozenset({"appointments.search", "appointments.get"})
SEARCH_ONLY = frozenset({"appointments.search"})
MARKER_A = {"observation": "tenant-a-slots"}
MARKER_B = {"observation": "tenant-b-slots"}


class AuditingExecutor(RecordingExecutor):
    """T03 recording executor plus the optional `audit_hook` the loop already uses."""

    def __init__(
        self,
        result: ToolResult[Any] | None = None,
        *,
        audit_hook: Callable[[ToolAuditEvent], None] | None = None,
    ) -> None:
        super().__init__(result)
        self._audit_hook = audit_hook
        self.events: list[ToolAuditEvent] = []

    async def execute(
        self,
        tenant: TenantContext,
        run_id: UUID,
        call: ToolCall,
        carrier: dict[str, str] | None = None,
    ) -> ToolResult[Any]:
        result = await super().execute(tenant, run_id, call, carrier)
        error_code = (
            None if result.ok or result.error is None else result.error.code
        )
        isolation = error_code == ToolErrorCode.TENANT_ISOLATION_VIOLATION
        event = ToolAuditEvent(
            run_id=run_id,
            tenant_id=tenant.tenant_id,
            tool=call.name,
            allowed=result.ok and not isolation,
            error_code=error_code,
        )
        self.events.append(event)
        if self._audit_hook is not None:
            self._audit_hook(event)
        return result


class _CatalogResolver:
    def __init__(self, allowed_tools: frozenset[str]) -> None:
        self._allowed = allowed_tools
        self.calls: list[tuple[UUID, str]] = []

    async def resolve(self, tenant: TenantContext, capability: str) -> McpTarget:
        self.calls.append((tenant.tenant_id, capability))
        return McpTarget(
            server_id="mcp-catalog",
            allowed_tools=self._allowed,
            endpoint="https://mcp.example/sse",
        )


class TenantCatalogFactory:
    """Builds a real `ToolExecutor` from each turn's `TenantContext` and catalog."""

    def __init__(self, catalogs: dict[UUID, frozenset[str]]) -> None:
        self.catalogs = dict(catalogs)
        self.tenants: list[TenantContext] = []
        self.executors: dict[UUID, ToolExecutor] = {}
        self.capabilities: dict[UUID, CapabilitySpy] = {}
        self.transports: dict[UUID, TransportSpy] = {}
        self.resolvers: dict[UUID, _CatalogResolver] = {}
        self.audits: dict[UUID, list[ToolAuditEvent]] = {}

    async def for_tenant(
        self, tenant: TenantContext, config: TenantConfig, skill: str
    ) -> ToolExecutor:
        del config, skill
        self.tenants.append(tenant)
        catalog = self.catalogs[tenant.tenant_id]
        capability = CapabilitySpy()
        capability.search.return_value = ToolResult[dict[str, object]](
            ok=True, value={"id": "slot-1"}
        )
        capability.get.return_value = ToolResult[dict[str, object]](
            ok=True, value={"id": "apt-1"}
        )
        transport = TransportSpy()
        resolver = _CatalogResolver(catalog)
        events: list[ToolAuditEvent] = []
        executor = ToolExecutor(
            server=catalog,
            tenant=catalog,
            skill=READ_SURFACE,
            capability=capability,
            resolver=resolver,
            audit_hook=events.append,
            allowed_hosts=("mcp.example",),
            transport=transport,
        )
        self.capabilities[tenant.tenant_id] = capability
        self.transports[tenant.tenant_id] = transport
        self.resolvers[tenant.tenant_id] = resolver
        self.audits[tenant.tenant_id] = events
        self.executors[tenant.tenant_id] = executor
        return executor


def _observation_values(llm: ScriptedLLM) -> list[object]:
    return [obs.value for request in llm.requests for obs in request.tool_results]


@pytest.mark.anyio
async def test_tenant_a_cannot_execute_tool_discovered_only_on_tenant_b_mcp() -> None:
    factory = TenantCatalogFactory(
        {
            TENANT_A: SEARCH_ONLY,
            TENANT_B: READ_SURFACE,
        }
    )
    llm = ScriptedLLM(GET_PROPOSAL, ANSWER)
    harness, _knowledge, _llm, _runs = make_loop_harness(llm=llm, executors=factory)

    result = await harness.handle_message(tenant_a(), inbound("hours"))

    assert [ctx.tenant_id for ctx in factory.tenants] == [TENANT_A]
    assert TENANT_B not in factory.executors
    factory.transports[TENANT_A].assert_not_called()
    factory.capabilities[TENANT_A].get.assert_not_called()
    factory.capabilities[TENANT_A].search.assert_not_called()
    factory.capabilities[TENANT_A].assert_not_called()
    events = factory.audits[TENANT_A]
    assert events
    assert all(event.allowed is False for event in events)
    assert all(event.error_code == ToolErrorCode.FORBIDDEN for event in events)
    assert all(event.tool == B_ONLY_DISCOVERED for event in events)
    assert all(event.run_id == result.run_id for event in events)
    assert all(event.tenant_id == tenant_a().tenant_id for event in events)
    assert result.tool_calls[0].ok is False
    assert result.tool_calls[0].error_code == "forbidden"
    assert llm.requests[1].tool_results[0].error_code == "forbidden"


@pytest.mark.anyio
async def test_concurrent_turns_use_distinct_executors_and_do_not_cross_observations() -> (
    None
):
    exec_a = RecordingExecutor(
        ToolResult[dict[str, object]](ok=True, value=MARKER_A)
    )
    exec_b = RecordingExecutor(
        ToolResult[dict[str, object]](ok=True, value=MARKER_B)
    )
    factory = PerTenantFactory({TENANT_A: exec_a, TENANT_B: exec_b})
    llm_a = ScriptedLLM(SEARCH_PROPOSAL, ANSWER)
    llm_b = ScriptedLLM(SEARCH_PROPOSAL, ANSWER)
    harness_a, _ka, _la, _ra = make_loop_harness(llm=llm_a, executors=factory)
    harness_b, _kb, _lb, _rb = make_loop_harness(llm=llm_b, executors=factory)

    result_a, result_b = await asyncio.gather(
        harness_a.handle_message(tenant_a(), inbound("hours")),
        harness_b.handle_message(tenant_b(), inbound("hours")),
    )

    assert exec_a is not exec_b
    assert {ctx.tenant_id for ctx in factory.tenants} == {TENANT_A, TENANT_B}
    assert all(ctx.tenant_id == TENANT_A for ctx in exec_a.tenants)
    assert all(ctx.tenant_id == TENANT_B for ctx in exec_b.tenants)
    assert exec_a.run_ids == [result_a.run_id]
    assert exec_b.run_ids == [result_b.run_id]
    assert MARKER_A in _observation_values(llm_a)
    assert MARKER_B in _observation_values(llm_b)
    assert MARKER_A not in _observation_values(llm_b)
    assert MARKER_B not in _observation_values(llm_a)
    assert all(request.tenant_id == TENANT_A for request in llm_a.requests)
    assert all(request.tenant_id == TENANT_B for request in llm_b.requests)


@pytest.mark.anyio
async def test_enlarging_tenant_a_allowlist_does_not_change_tenant_b_surface() -> None:
    factory = TenantCatalogFactory(
        {
            TENANT_A: SEARCH_ONLY,
            TENANT_B: SEARCH_ONLY,
        }
    )
    llm_b_before = ScriptedLLM(SEARCH_PROPOSAL, ANSWER)
    harness_b, _k, _l, _r = make_loop_harness(llm=llm_b_before, executors=factory)
    before = await harness_b.handle_message(tenant_b(), inbound("hours"))
    surface_before = factory.catalogs[TENANT_B]
    built_for_b = [ctx.tenant_id for ctx in factory.tenants]
    assert before.tool_calls[0].ok is True
    assert surface_before == SEARCH_ONLY
    assert TENANT_B in built_for_b

    factory.catalogs[TENANT_A] = READ_SURFACE

    llm_b_after = ScriptedLLM(GET_PROPOSAL, ANSWER)
    harness_b_after, _k2, _l2, _r2 = make_loop_harness(
        llm=llm_b_after, executors=factory
    )
    after_b = await harness_b_after.handle_message(tenant_b(), inbound("hours"))

    assert factory.catalogs[TENANT_B] == SEARCH_ONLY
    factory.transports[TENANT_B].assert_not_called()
    factory.capabilities[TENANT_B].get.assert_not_called()
    assert after_b.tool_calls[0].ok is False
    assert after_b.tool_calls[0].error_code == "forbidden"
    assert all(event.allowed is False for event in factory.audits[TENANT_B])
    assert all(event.tenant_id == TENANT_B for event in factory.audits[TENANT_B])

    llm_a = ScriptedLLM(GET_PROPOSAL, ANSWER)
    harness_a, _k3, _l3, _r3 = make_loop_harness(llm=llm_a, executors=factory)
    after_a = await harness_a.handle_message(tenant_a(), inbound("hours"))
    assert after_a.tool_calls[0].ok is True
    assert after_a.tool_calls[0].name == B_ONLY_DISCOVERED
    factory.transports[TENANT_A].call_tool.assert_awaited()
    factory.capabilities[TENANT_A].get.assert_not_called()
    assert factory.catalogs[TENANT_B] == SEARCH_ONLY


@pytest.mark.anyio
async def test_tenant_isolation_violation_aborts_without_model_feedback() -> None:
    events: list[ToolAuditEvent] = []
    executor = AuditingExecutor(
        error_result(
            ToolErrorCode.TENANT_ISOLATION_VIOLATION,
            "An internal error occurred.",
        ),
        audit_hook=events.append,
    )
    llm = ScriptedLLM(SEARCH_PROPOSAL, ANSWER)
    harness, _knowledge, _llm, runs = make_loop_harness(
        llm=llm, executors=RecordingFactory(executor)
    )

    result = await harness.handle_message(tenant_a(), inbound("hours"))

    assert len(llm.requests) == 1
    assert llm.requests[0].tool_results == ()
    assert result.kind == "insufficient"
    assert result.text == SAFE_INSUFFICIENT
    assert "Hours are 8 to 16" not in result.text
    assert runs.finished and runs.finished[0][1] == "failed"
    assert runs.error_codes == ["tenant_isolation_violation"]
    assert events
    assert all(event.allowed is False for event in events)
    assert all(
        event.error_code == ToolErrorCode.TENANT_ISOLATION_VIOLATION
        for event in events
    )
    assert all(event.run_id == result.run_id for event in events)
    assert all(event.tenant_id == tenant_a().tenant_id for event in events)


@pytest.mark.anyio
async def test_tool_audit_events_carry_turn_run_id_and_tenant() -> None:
    events: list[ToolAuditEvent] = []
    executor = AuditingExecutor(
        ToolResult[dict[str, object]](ok=True, value={"slots": 2}),
        audit_hook=events.append,
    )
    llm = ScriptedLLM(SEARCH_PROPOSAL, ANSWER)
    configs = FakeConfigRepository(
        {
            TENANT_A: TenantConfig(
                tenant_id=TENANT_A,
                version=1,
                agent=AgentConfig(tone="cordial"),
                enabled_skills=frozenset({"faq"}),  # type: ignore[arg-type]
                enabled_tools=SEARCH_ONLY,
            ),
            TENANT_B: config_for(TENANT_B, frozenset({"faq"})),
        }
    )
    harness, _knowledge, _llm, _runs = make_loop_harness(
        llm=llm, executors=RecordingFactory(executor), configs=configs
    )

    result = await harness.handle_message(tenant_a(), inbound("hours"))

    assert events
    assert result.run_id is not None
    for event in events:
        assert event.run_id == result.run_id
        assert event.tenant_id == tenant_a().tenant_id
        assert event.tenant_id != TENANT_B
