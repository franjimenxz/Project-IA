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


def test_available_tools_are_three_way_intersection() -> None:
    assert registry.available(
        server={"appointments.search", "appointments.create"},
        tenant={"appointments.search"},
        skill={"appointments.search", "appointments.cancel"},
    ) == frozenset({"appointments.search"})


def test_discovered_tool_in_intersection_is_allowed() -> None:
    discovered = "crear_turno"
    caps = {discovered, "appointments.search"}
    assert discovered not in registry.KNOWN_TOOLS
    assert registry.available(server=caps, tenant=caps, skill=caps) == frozenset(caps)
    assert registry.authorize(discovered, server=caps, tenant=caps, skill=caps) == discovered


def test_available_requires_server_dimension() -> None:
    name = "crear_turno"
    tenant_and_skill = {name, "appointments.search"}
    assert name not in registry.available(
        server={"appointments.search"},
        tenant=tenant_and_skill,
        skill=tenant_and_skill,
    )
    with pytest.raises(ForbiddenTool) as caught:
        registry.authorize(
            name,
            server={"appointments.search"},
            tenant=tenant_and_skill,
            skill=tenant_and_skill,
        )
    assert caught.value.code == ToolErrorCode.FORBIDDEN


def test_disabled_tool_is_forbidden() -> None:
    with pytest.raises(ForbiddenTool) as caught:
        registry.authorize(
            "appointments.create",
            server={"appointments.search", "appointments.create"},
            tenant={"appointments.search"},
            skill={"appointments.search", "appointments.create"},
        )
    assert caught.value.code == ToolErrorCode.FORBIDDEN


def test_tool_outside_skill_allowlist_is_forbidden() -> None:
    with pytest.raises(ForbiddenTool) as caught:
        registry.authorize(
            "appointments.create",
            server={"appointments.search", "appointments.create"},
            tenant={"appointments.search", "appointments.create"},
            skill={"appointments.search"},
        )
    assert caught.value.code == ToolErrorCode.FORBIDDEN


def test_tenant_a_does_not_see_tenant_b_exclusive_tools() -> None:
    tenant_a = registry.available(
        server=CATALOG,
        tenant=TENANT_A_TOOLS,
        skill=CATALOG,
    )
    tenant_b = registry.available(
        server=CATALOG,
        tenant=TENANT_A_TOOLS | {TENANT_B_EXCLUSIVE},
        skill=CATALOG,
    )
    assert TENANT_B_EXCLUSIVE not in tenant_a
    assert TENANT_B_EXCLUSIVE in tenant_b
    with pytest.raises(ForbiddenTool) as caught:
        registry.authorize(
            TENANT_B_EXCLUSIVE,
            server=CATALOG,
            tenant=TENANT_A_TOOLS,
            skill=CATALOG,
        )
    assert caught.value.code == ToolErrorCode.FORBIDDEN


def test_authorize_does_not_call_executor() -> None:
    executed = False

    def executor() -> None:
        nonlocal executed
        executed = True
        raise AssertionError("executor must not run")

    with pytest.raises(ForbiddenTool):
        registry.authorize(
            "appointments.create",
            server={"appointments.search", "appointments.create"},
            tenant={"appointments.search"},
            skill={"appointments.search", "appointments.create"},
        )
        executor()

    assert executed is False


def test_authorize_returns_str_compatible_tool_name() -> None:
    name = registry.authorize(
        "appointments.search",
        server={"appointments.search", "appointments.create"},
        tenant={"appointments.search"},
        skill={"appointments.search", "appointments.cancel"},
    )
    assert name == "appointments.search"
    assert isinstance(name, str)
