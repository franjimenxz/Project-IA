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


def test_unknown_tool_is_forbidden() -> None:
    unknown = "appointments.explode"
    caps = {unknown, *CATALOG}
    assert unknown not in registry.available(server=caps, tenant=caps, skill=caps)
    with pytest.raises(ForbiddenTool) as caught:
        registry.authorize(unknown, server=caps, tenant=caps, skill=caps)
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
