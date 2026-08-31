from uuid import UUID

import pytest

from ia_mcp.configuration.models import AgentConfig, TenantConfig
from ia_mcp.mcp.registry import KNOWN_TOOLS, ToolName
from ia_mcp.skills.registry import SkillNotAuthorized, SkillRegistry

TENANT_A = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")


def _config(
    *skills: str, enabled_tools: frozenset[str] | None = None
) -> TenantConfig:
    kwargs: dict[str, object] = {}
    if enabled_tools is not None:
        kwargs["enabled_tools"] = enabled_tools
    return TenantConfig(
        tenant_id=TENANT_A,
        version=1,
        agent=AgentConfig(tone="cordial"),
        enabled_skills=frozenset(skills),  # type: ignore[arg-type]
        **kwargs,  # type: ignore[arg-type]
    )


def test_unknown_skill_fails_closed() -> None:
    registry = SkillRegistry()
    with pytest.raises(SkillNotAuthorized) as caught:
        registry.resolve("billing", _config("faq"))  # type: ignore[arg-type]
    assert caught.value.code == "skill_not_authorized"


def test_disabled_skill_is_not_instantiated() -> None:
    registry = SkillRegistry()
    with pytest.raises(SkillNotAuthorized):
        registry.resolve("appointments", _config("faq"))


def test_faq_exposes_enabled_tools_including_discovered_names() -> None:
    config = _config("faq", enabled_tools=frozenset({"crear_turno"}))
    skill = SkillRegistry().resolve("faq", config)
    assert skill.name == "faq"
    assert skill.allowed_tools(config) == frozenset({ToolName("crear_turno")})


def test_appointments_uses_tenant_allowlist_including_discovered_names() -> None:
    config = _config(
        "appointments",
        enabled_tools=frozenset({"crear_turno", "appointments.search"}),
    )
    skill = SkillRegistry().resolve("appointments", config)
    allowed = skill.allowed_tools(config)
    assert ToolName("crear_turno") in allowed
    assert ToolName("appointments.search") in allowed
    assert ToolName("crear_turno") not in KNOWN_TOOLS


def test_appointments_does_not_clamp_to_known_tools() -> None:
    config = _config("appointments")
    skill = SkillRegistry().resolve("appointments", config)
    assert skill.allowed_tools(config) != KNOWN_TOOLS
