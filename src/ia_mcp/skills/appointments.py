from ia_mcp.configuration.models import SkillName, TenantConfig
from ia_mcp.mcp.registry import ToolName
from ia_mcp.skills.base import FieldSpec, SkillResult, SkillTurn


class AppointmentSkill:
    name: SkillName = "appointments"

    def required_fields(self, config: TenantConfig) -> tuple[FieldSpec, ...]:
        return tuple(
            FieldSpec(name=name, required=True)
            for name in config.appointments.required_fields
        )

    def allowed_tools(self, config: TenantConfig) -> frozenset[ToolName]:
        del config
        return frozenset({ToolName("appointments.search")})

    async def route(self, turn: SkillTurn) -> SkillResult:
        del turn
        return SkillResult(kind="appointments")
