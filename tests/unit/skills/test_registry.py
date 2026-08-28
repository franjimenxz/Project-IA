from uuid import UUID

import pytest

from ia_mcp.configuration.models import AgentConfig, TenantConfig
from ia_mcp.mcp.registry import ToolName
from ia_mcp.skills.registry import SkillNotAuthorized, SkillRegistry

TENANT_A = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")


def _config(*skills: str) -> TenantConfig:
    return TenantConfig(
        tenant_id=TENANT_A,
        version=1,
        agent=AgentConfig(tone="cordial"),
        enabled_skills=frozenset(skills),  # type: ignore[arg-type]
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


def test_faq_exposes_no_tools() -> None:
    skill = SkillRegistry().resolve("faq", _config("faq"))
    assert skill.name == "faq"
    assert skill.allowed_tools(_config("faq")) == frozenset()


def test_appointments_exposes_canonical_tools_when_enabled() -> None:
    config = _config("appointments")
    skill = SkillRegistry().resolve("appointments", config)
    assert ToolName("appointments.search") in skill.allowed_tools(config)
    assert ToolName("appointments.create") in skill.allowed_tools(config)
