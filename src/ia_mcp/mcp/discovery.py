from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

from ia_mcp.tenancy.models import TenantContext


@dataclass(frozen=True, slots=True)
class DiscoveredTool:
    name: str
    description: str = ""
    input_schema: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class McpEndpoint:
    server_id: str
    endpoint: str
    auth_reference: str = ""


class ToolCatalog:
    def __init__(self, tools: Iterable[DiscoveredTool]) -> None:
        self._tools = tuple(tools)

    def names(self) -> frozenset[str]:
        return frozenset(tool.name for tool in self._tools)

    def tools(self) -> tuple[DiscoveredTool, ...]:
        return self._tools


class McpDiscovery(Protocol):
    async def list_tools(
        self, tenant: TenantContext, target: McpEndpoint
    ) -> ToolCatalog: ...
