import asyncio
from collections.abc import Coroutine
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from ia_mcp.contracts.common import ToolResult
from ia_mcp.contracts.errors import ToolErrorCode
from ia_mcp.mcp import registry
from ia_mcp.mcp.executor import McpTarget, ToolCall, ToolExecutor
from ia_mcp.mcp.registry import ForbiddenTool
from ia_mcp.tenancy.models import TenantContext

CATALOG = {
    "appointments.search",
    "appointments.get",
    "appointments.create",
    "appointments.cancel",
    "appointments.reschedule",
    "appointments.confirm",
}
TENANT_A_TOOLS = {
    "appointments.search",
    "appointments.get",
    "appointments.create",
}
TENANT_B_EXCLUSIVE = "appointments.confirm"


def test_tenant_a_cannot_see_tenant_b_exclusive_tools() -> None:
    available = registry.available(
        server=CATALOG,
        tenant=TENANT_A_TOOLS,
        skill=CATALOG,
    )
    assert TENANT_B_EXCLUSIVE not in available
    with pytest.raises(ForbiddenTool) as caught:
        registry.authorize(
            TENANT_B_EXCLUSIVE,
            server=CATALOG,
            tenant=TENANT_A_TOOLS,
            skill=CATALOG,
        )
    assert caught.value.code == ToolErrorCode.FORBIDDEN


def test_discovered_tool_in_intersection_is_allowed() -> None:
    discovered = "appointments.explode"
    caps = {discovered, *CATALOG}
    assert discovered not in registry.KNOWN_TOOLS
    assert discovered in registry.available(server=caps, tenant=caps, skill=caps)
    assert registry.authorize(discovered, server=caps, tenant=caps, skill=caps) == discovered


def test_available_requires_server_dimension() -> None:
    discovered = "appointments.explode"
    tenant_and_skill = {discovered, *CATALOG}
    assert discovered not in registry.available(
        server=CATALOG,
        tenant=tenant_and_skill,
        skill=tenant_and_skill,
    )
    with pytest.raises(ForbiddenTool) as caught:
        registry.authorize(
            discovered,
            server=CATALOG,
            tenant=tenant_and_skill,
            skill=tenant_and_skill,
        )
    assert caught.value.code == ToolErrorCode.FORBIDDEN


def _run[T](coro: Coroutine[object, object, T]) -> T:
    return asyncio.run(coro)


class _CapabilitySpy:
    def __init__(self) -> None:
        self.search = AsyncMock(return_value=ToolResult[list[object]](ok=True, value=[]))
        self.get = AsyncMock()
        self.create = AsyncMock()
        self.cancel = AsyncMock()
        self.reschedule = AsyncMock()
        self.confirm = AsyncMock()


class _TransportSpy:
    def __init__(self) -> None:
        self.call_tool = AsyncMock(
            return_value=ToolResult[dict[str, str]](ok=True, value={"ok": "yes"})
        )


class _Resolver:
    def __init__(self, *, endpoint: str, allowed_tools: frozenset[str]) -> None:
        self._target = McpTarget(
            server_id="mcp-sec",
            allowed_tools=allowed_tools,
            endpoint=endpoint,
        )

    async def resolve(self, tenant: TenantContext, capability: str) -> McpTarget:
        assert tenant.tenant_id
        return self._target


def test_disabled_tool_is_forbidden() -> None:
    disabled = "appointments.cancel"
    available = registry.available(
        server=CATALOG,
        tenant=TENANT_A_TOOLS,
        skill=CATALOG,
    )
    assert disabled not in available
    with pytest.raises(ForbiddenTool) as caught:
        registry.authorize(
            disabled,
            server=CATALOG,
            tenant=TENANT_A_TOOLS,
            skill=CATALOG,
        )
    assert caught.value.code == ToolErrorCode.FORBIDDEN


def _tenant() -> TenantContext:
    return TenantContext(
        tenant_id=uuid4(),
        tenant_slug="tenant-a",
        config_version=1,
        correlation_id=uuid4(),
    )


def _executor(
    *,
    transport: _TransportSpy,
    endpoint: str,
    server: set[str],
    tenant: set[str],
    skill: set[str],
    allowed_hosts: frozenset[str],
) -> ToolExecutor:
    return ToolExecutor(
        server=server,
        tenant=tenant,
        skill=skill,
        capability=_CapabilitySpy(),
        resolver=_Resolver(endpoint=endpoint, allowed_tools=frozenset(server)),
        transport=transport,
        allowed_hosts=allowed_hosts,
    )


@pytest.mark.security
def test_host_not_allowlisted_never_invokes_transport() -> None:
    transport = _TransportSpy()
    discovered = "crear_turno"
    tools = {discovered, *CATALOG}
    executor = _executor(
        transport=transport,
        endpoint="https://evil.example/sse",
        server=tools,
        tenant=tools,
        skill=tools,
        allowed_hosts=frozenset({"mcp.example"}),
    )
    result = _run(
        executor.execute(
            _tenant(),
            uuid4(),
            ToolCall(name=discovered, arguments={"slot": "manana"}),
        )
    )
    assert result.ok is False
    assert result.error is not None
    assert result.error.code == ToolErrorCode.FORBIDDEN
    transport.call_tool.assert_not_called()


@pytest.mark.security
def test_tool_outside_intersection_never_invokes_transport() -> None:
    transport = _TransportSpy()
    discovered = "crear_turno"
    executor = _executor(
        transport=transport,
        endpoint="https://mcp.example/sse",
        server={discovered, *CATALOG},
        tenant=TENANT_A_TOOLS,
        skill={discovered, *CATALOG},
        allowed_hosts=frozenset({"mcp.example"}),
    )
    result = _run(
        executor.execute(
            _tenant(),
            uuid4(),
            ToolCall(name=discovered, arguments={"slot": "manana"}),
        )
    )
    assert result.ok is False
    assert result.error is not None
    assert result.error.code == ToolErrorCode.FORBIDDEN
    transport.call_tool.assert_not_called()


@pytest.mark.security
def test_transport_without_allowed_hosts_cannot_build() -> None:
    transport = _TransportSpy()
    discovered = "crear_turno"
    tools = {discovered, *CATALOG}
    with pytest.raises(ValueError) as caught:
        ToolExecutor(
            server=tools,
            tenant=tools,
            skill=tools,
            capability=_CapabilitySpy(),
            resolver=_Resolver(
                endpoint="http://evil.example/sse",
                allowed_tools=frozenset(tools),
            ),
            transport=transport,
        )
    assert "allowed_hosts" in str(caught.value)
    transport.call_tool.assert_not_called()
