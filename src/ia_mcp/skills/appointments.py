from ia_mcp.configuration.models import SkillName, TenantConfig
from ia_mcp.mcp.registry import ToolName
from ia_mcp.skills.base import FieldSpec, SkillResult, SkillTurn


def configured_tool_allowlist(config: TenantConfig) -> frozenset[ToolName]:
    raw = getattr(config, "enabled_tools", None)
    if not raw:
        return frozenset()
    return frozenset(ToolName(str(name)) for name in raw)


class AppointmentSkill:
    name: SkillName = "appointments"

    def required_fields(self, config: TenantConfig) -> tuple[FieldSpec, ...]:
        return tuple(
            FieldSpec(name=name, required=True)
            for name in config.appointments.required_fields
        )

    def allowed_tools(self, config: TenantConfig) -> frozenset[ToolName]:
        return configured_tool_allowlist(config)

    async def route(self, turn: SkillTurn) -> SkillResult:
        del turn
        return SkillResult(kind="appointments")
