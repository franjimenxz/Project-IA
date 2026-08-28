from __future__ import annotations

import inspect
from typing import get_type_hints

from ia_mcp.mcp.discovery import (
    DiscoveredTool,
    McpDiscovery,
    McpEndpoint,
    ToolCatalog,
)
from ia_mcp.tenancy.models import TenantContext


def test_tool_catalog_exposes_names_and_tools() -> None:
    tools = (
        DiscoveredTool(name="crear_turno", description="Create a slot"),
        DiscoveredTool(name="buscar_eventos", description="Search events"),
    )
    catalog = ToolCatalog(tools)
    assert catalog.names() == frozenset({"crear_turno", "buscar_eventos"})
    assert catalog.tools() == tools


def test_mcp_endpoint_stores_auth_reference_without_extra_fields() -> None:
    target = McpEndpoint(
        server_id="lan-mcp",
        endpoint="http://127.0.0.1:9/sse",
        auth_reference="ref://vault/mcp",
    )
    assert target.server_id == "lan-mcp"
    assert target.endpoint == "http://127.0.0.1:9/sse"
    assert target.auth_reference == "ref://vault/mcp"


def test_mcp_discovery_protocol_requires_tenant_and_target() -> None:
    hints = get_type_hints(McpDiscovery.list_tools)
    assert hints["tenant"] is TenantContext
    assert hints["target"] is McpEndpoint
    assert hints["return"] is ToolCatalog
    parameters = inspect.signature(McpDiscovery.list_tools).parameters
    assert tuple(parameters) == ("self", "tenant", "target")
