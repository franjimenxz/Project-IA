import pytest

from ia_mcp.contracts.errors import ToolErrorCode
from ia_mcp.mcp import registry
from ia_mcp.mcp.registry import ForbiddenTool

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
