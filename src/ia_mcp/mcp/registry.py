from collections.abc import Iterable
from typing import NewType

from ia_mcp.contracts.errors import ToolErrorCode

ToolName = NewType("ToolName", str)

KNOWN_TOOLS: frozenset[ToolName] = frozenset(
    {
        ToolName("appointments.search"),
        ToolName("appointments.get"),
        ToolName("appointments.create"),
        ToolName("appointments.cancel"),
        ToolName("appointments.reschedule"),
        ToolName("appointments.confirm"),
    }
)


class ForbiddenTool(Exception):
    def __init__(self, tool: str) -> None:
        self.tool = tool
        self.code = ToolErrorCode.FORBIDDEN
        super().__init__("Action is not allowed.")


def available(
    server: Iterable[str],
    tenant: Iterable[str],
    skill: Iterable[str],
) -> frozenset[str]:
    return frozenset(server) & frozenset(tenant) & frozenset(skill)


def authorize(
    tool: str,
    *,
    server: Iterable[str],
    tenant: Iterable[str],
    skill: Iterable[str],
) -> ToolName:
    if tool not in available(server, tenant, skill):
        raise ForbiddenTool(tool)
    return ToolName(tool)
