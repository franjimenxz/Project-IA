"""Composition root wiring matrix.

No PostgreSQL is required: `create_async_engine` is lazy, so the graph can be
built against an unreachable URL as long as nothing issues a query. Coroutines
are wrapped with `asyncio.run` because pytest-asyncio is not installed.
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from ia_mcp.agent_runtime.harness import AgentHarness
from ia_mcp.api.app import create_app
from ia_mcp.api.composition import (
    TenantToolExecutors,
    allowed_hosts_for,
    build_runtime,
    mcp_endpoints_from,
)
from ia_mcp.configuration.models import AgentConfig, TenantConfig
from ia_mcp.configuration.service import ConfigurationService
from ia_mcp.contracts.common import ToolResult
from ia_mcp.contracts.errors import ToolErrorCode
from ia_mcp.mcp.client import SseMcpClient
from ia_mcp.mcp.executor import McpTarget, ToolCall
from ia_mcp.mcp.fakes.appointments import FakeAppointmentCapability
from ia_mcp.skills.registry import SkillRegistry
from ia_mcp.tenancy.models import TenantContext
from ia_mcp.tenancy.service import TenantService
from tests.integration.api.test_simulated_messages import (
    FROZEN_NOW,
    FakeChannelRepository,
    signed_simulated_headers,
    valid_body,
)

# Port 1 is never a PostgreSQL listener; the graph must not connect while building.
UNREACHABLE_DATABASE_URL = "postgresql+psycopg://ia_mcp@127.0.0.1:1/ia_mcp_composition"
MCP_HOST = "mcp.example"
MCP_ENDPOINT = f"https://{MCP_HOST}/sse"
SERVER_ID = "mcp-appointments"
TENANT_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
RUN_ID = uuid4()
GENERIC_TOOL = "crear_turno"
SEARCH_ARGS: dict[str, Any] = {
    "specialty": "cardiologia",
    "date_from": "2026-09-01",
    "date_to": "2026-09-01",
}

RUNTIME_STATE = (
    "tenant_service",
    "config_service",
    "agent_harness",
    "channel_integration_ids",
    "tool_executor",
)


def _run[T](coro: Coroutine[object, object, T]) -> T:
    return asyncio.run(coro)


def _tenant() -> TenantContext:
    return TenantContext(
        tenant_id=TENANT_ID,
        tenant_slug="tenant-a",
        config_version=1,
        correlation_id=uuid4(),
    )


def _config(*enabled_tools: str) -> TenantConfig:
    return TenantConfig(
        tenant_id=TENANT_ID,
        version=1,
        agent=AgentConfig(tone="cordial"),
        enabled_skills=frozenset({"appointments"}),
        enabled_tools=frozenset(enabled_tools),
    )


class StubIntegrations:
    """MCP server the tenant declared, with the tools it declared for it."""

    def __init__(self, tools: frozenset[str]) -> None:
        self._tools = tools
        self.tenants: list[TenantContext] = []

    async def declared_tools(self, tenant: TenantContext) -> frozenset[str]:
        self.tenants.append(tenant)
        return self._tools

    async def resolve(self, tenant: TenantContext, capability: str) -> McpTarget:
        del tenant, capability
        return McpTarget(
            server_id=SERVER_ID,
            allowed_tools=self._tools,
            endpoint=MCP_ENDPOINT,
            auth_reference="",
        )


class TransportSpy:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def call_tool(
        self,
        tenant: TenantContext,
        target: McpTarget,
        name: str,
        arguments: dict[str, Any],
    ) -> ToolResult[Any]:
        del tenant, target, arguments
        self.calls.append(name)
        return ToolResult[Any](ok=True, value={"status": "ok"})


def _executors(
    *,
    declared: frozenset[str],
    transport: TransportSpy | None = None,
    allowed_hosts: tuple[str, ...] = (),
) -> TenantToolExecutors:
    return TenantToolExecutors(
        integrations=StubIntegrations(declared),
        capability=FakeAppointmentCapability(),
        skills=SkillRegistry(),
        allowed_hosts=allowed_hosts,
        transport=transport,
    )


def test_test_environment_does_not_autowire(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", UNREACHABLE_DATABASE_URL)
    app = create_app(environment="test")
    for name in RUNTIME_STATE:
        assert getattr(app.state, name, None) is None


def test_development_without_database_url_does_not_autowire(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    app = create_app(environment="development")
    for name in RUNTIME_STATE:
        assert getattr(app.state, name, None) is None


def test_development_with_database_url_attaches_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", UNREACHABLE_DATABASE_URL)
    app = create_app(environment="development")
    assert isinstance(app.state.tenant_service, TenantService)
    assert isinstance(app.state.config_service, ConfigurationService)
    assert isinstance(app.state.agent_harness, AgentHarness)
    assert isinstance(app.state.channel_integration_ids, dict)
    assert isinstance(app.state.tool_executor, TenantToolExecutors)


def test_production_mounts_no_simulated_route_and_no_fakes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", UNREACHABLE_DATABASE_URL)
    app = create_app(environment="production")
    paths = {getattr(route, "path", "") for route in app.routes}
    assert "/v1/simulated/messages" not in paths
    for name in RUNTIME_STATE:
        assert getattr(app.state, name, None) is None


def test_injected_tenant_service_still_acknowledges_in_test_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", UNREACHABLE_DATABASE_URL)
    app = create_app(environment="test")
    app.state.tenant_service = TenantService(
        FakeChannelRepository({("simulated", "acct-a"): TENANT_ID})
    )
    app.state.simulated_clock = lambda: FROZEN_NOW
    body = valid_body()
    response = TestClient(app).post(
        "/v1/simulated/messages",
        json=body,
        headers=signed_simulated_headers(account="acct-a", body=body),
    )
    assert response.status_code == 202
    assert "run_id" not in response.json()


def test_runtime_builds_generic_transport_from_configured_endpoints() -> None:
    runtime = build_runtime(
        environment="development",
        environ={
            "DATABASE_URL": UNREACHABLE_DATABASE_URL,
            "IA_MCP_MCP_ENDPOINTS": f"{SERVER_ID}={MCP_ENDPOINT}",
        },
    )
    assert runtime is not None
    assert isinstance(runtime.tool_executor.transport, SseMcpClient)
    assert runtime.tool_executor.allowed_hosts == (MCP_HOST,)


def test_runtime_without_configured_endpoints_has_no_generic_transport() -> None:
    runtime = build_runtime(
        environment="development",
        environ={"DATABASE_URL": UNREACHABLE_DATABASE_URL},
    )
    assert runtime is not None
    assert runtime.tool_executor.transport is None
    assert runtime.tool_executor.allowed_hosts == ()


def test_generic_transport_requires_allowed_hosts() -> None:
    with pytest.raises(ValueError) as caught:
        _executors(declared=frozenset({GENERIC_TOOL}), transport=TransportSpy())
    assert "allowed_hosts" in str(caught.value)


def test_executor_intersects_tenant_config_with_declared_catalog() -> None:
    executors = _executors(declared=frozenset({"appointments.search", GENERIC_TOOL}))
    tenant = _tenant()

    async def _scenario() -> tuple[ToolResult[Any], ToolResult[Any]]:
        executor = await executors.for_tenant(
            tenant, _config("appointments.search"), "appointments"
        )
        allowed = await executor.execute(
            tenant, RUN_ID, ToolCall(name="appointments.search", arguments=SEARCH_ARGS)
        )
        denied = await executor.execute(
            tenant, RUN_ID, ToolCall(name=GENERIC_TOOL, arguments={})
        )
        return allowed, denied

    allowed, denied = _run(_scenario())
    assert allowed.ok is True
    assert denied.ok is False
    assert denied.error is not None
    assert denied.error.code == ToolErrorCode.FORBIDDEN


def test_authorized_generic_tool_reaches_the_mcp_client() -> None:
    transport = TransportSpy()
    executors = _executors(
        declared=frozenset({GENERIC_TOOL}),
        transport=transport,
        allowed_hosts=(MCP_HOST,),
    )
    tenant = _tenant()

    async def _scenario() -> ToolResult[Any]:
        executor = await executors.for_tenant(
            tenant, _config(GENERIC_TOOL), "appointments"
        )
        return await executor.execute(
            tenant, RUN_ID, ToolCall(name=GENERIC_TOOL, arguments={})
        )

    result = _run(_scenario())
    assert result.ok is True
    assert transport.calls == [GENERIC_TOOL]


def test_generic_tool_is_forbidden_without_transport() -> None:
    executors = _executors(declared=frozenset({GENERIC_TOOL}))
    tenant = _tenant()

    async def _scenario() -> ToolResult[Any]:
        executor = await executors.for_tenant(
            tenant, _config(GENERIC_TOOL), "appointments"
        )
        return await executor.execute(
            tenant, RUN_ID, ToolCall(name=GENERIC_TOOL, arguments={})
        )

    result = _run(_scenario())
    assert result.ok is False
    assert result.error is not None
    assert result.error.code == ToolErrorCode.FORBIDDEN


def test_endpoints_are_read_from_the_environment_not_hardcoded() -> None:
    endpoints = mcp_endpoints_from(
        {"IA_MCP_MCP_ENDPOINTS": f"{SERVER_ID}={MCP_ENDPOINT}, lan=http://lan.example"}
    )
    assert endpoints == {SERVER_ID: MCP_ENDPOINT, "lan": "http://lan.example"}
    assert allowed_hosts_for(endpoints) == (MCP_HOST, "http://lan.example")
    assert mcp_endpoints_from({}) == {}
