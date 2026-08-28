from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

from ia_mcp.mcp.executor import McpTarget
from ia_mcp.tenancy.models import TenantContext


@dataclass(frozen=True, slots=True)
class DiscoveredTool:
    name: str
    description: str = ""
    input_schema: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class DiscoveredToolCatalog:
    server_id: str
    tools: tuple[DiscoveredTool, ...]

    def names(self) -> frozenset[str]:
        return frozenset(tool.name for tool in self.tools)


class McpDiscovery(Protocol):
    async def list_tools(
        self, tenant: TenantContext, target: McpTarget
    ) -> DiscoveredToolCatalog: ...
