from __future__ import annotations

import inspect
from typing import get_type_hints

from ia_mcp.mcp.discovery import DiscoveredTool, DiscoveredToolCatalog, McpDiscovery
from ia_mcp.mcp.executor import McpTarget
from ia_mcp.tenancy.models import TenantContext


def test_discovered_tool_catalog_exposes_names_and_tools() -> None:
    tools = (
        DiscoveredTool(name="crear_turno", description="Create a slot"),
        DiscoveredTool(name="buscar_eventos", description="Search events"),
    )
    catalog = DiscoveredToolCatalog(server_id="lan-mcp", tools=tools)
    assert catalog.server_id == "lan-mcp"
    assert catalog.names() == frozenset({"crear_turno", "buscar_eventos"})
    assert catalog.tools == tools


def test_mcp_target_carries_allowed_tools_and_auth_reference() -> None:
    target = McpTarget(
        server_id="lan-mcp",
        endpoint="http://127.0.0.1:9/sse",
        auth_reference="ref://vault/mcp",
        allowed_tools=frozenset({"crear_turno"}),
    )
    assert target.server_id == "lan-mcp"
    assert target.endpoint == "http://127.0.0.1:9/sse"
    assert target.auth_reference == "ref://vault/mcp"
    assert target.allowed_tools == frozenset({"crear_turno"})


def test_mcp_discovery_protocol_requires_tenant_and_target() -> None:
    hints = get_type_hints(McpDiscovery.list_tools)
    assert hints["tenant"] is TenantContext
    assert hints["target"] is McpTarget
    assert hints["return"] is DiscoveredToolCatalog
    parameters = inspect.signature(McpDiscovery.list_tools).parameters
    assert tuple(parameters) == ("self", "tenant", "target")
