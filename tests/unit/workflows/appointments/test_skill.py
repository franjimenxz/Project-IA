from uuid import UUID

import pytest

from ia_mcp.configuration.models import AgentConfig, AppointmentPolicy, TenantConfig
from ia_mcp.mcp.registry import ToolName
from ia_mcp.skills.appointments import AppointmentSkill
from ia_mcp.skills.base import SkillTurn
from ia_mcp.tenancy.models import TenantContext

TENANT_A = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
TENANT_B = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")


def _config(tenant_id: UUID, required: tuple[str, ...]) -> TenantConfig:
    return TenantConfig(
        tenant_id=tenant_id,
        version=1,
        agent=AgentConfig(tone="cordial"),
        enabled_skills=frozenset({"appointments"}),
        appointments=AppointmentPolicy(required_fields=required),
    )


def test_allowed_tools_are_search_only() -> None:
    skill = AppointmentSkill()
    config = _config(TENANT_A, ("specialty", "date_from", "date_to"))
    assert skill.name == "appointments"
    assert skill.allowed_tools(config) == frozenset({ToolName("appointments.search")})
    assert ToolName("appointments.create") not in skill.allowed_tools(config)
    assert ToolName("appointments.cancel") not in skill.allowed_tools(config)


@pytest.mark.anyio
async def test_route_kind_is_appointments() -> None:
    tenant = TenantContext(
        tenant_id=TENANT_A,
        tenant_slug="tenant-a",
        config_version=1,
        correlation_id=UUID("33333333-3333-3333-3333-333333333333"),
    )
    result = await AppointmentSkill().route(SkillTurn(tenant=tenant, text="turno"))
    assert result.kind == "appointments"


@pytest.mark.parametrize(
    ("tenant_id", "required", "unexpected"),
    [
        (
            TENANT_A,
            ("specialty", "date_from", "date_to"),
            ("practitioner", "coverage"),
        ),
        (
            TENANT_B,
            ("specialty", "practitioner", "date_from", "date_to", "coverage"),
            (),
        ),
    ],
    ids=["tenant-a", "tenant-b"],
)
def test_required_fields_match_tenant_policy(
    tenant_id: UUID, required: tuple[str, ...], unexpected: tuple[str, ...]
) -> None:
    skill = AppointmentSkill()
    config = _config(tenant_id, required)
    names = tuple(spec.name for spec in skill.required_fields(config))
    assert names == required
    for name in unexpected:
        assert name not in names
