from ia_mcp.configuration.models import SkillName, TenantConfig
from ia_mcp.mcp.registry import ToolName
from ia_mcp.skills.appointments import configured_tool_allowlist
from ia_mcp.skills.base import FieldSpec, Skill, SkillResult, SkillTurn


class SkillNotAuthorized(Exception):
    def __init__(self, name: str) -> None:
        self.name = name
        self.code = "skill_not_authorized"
        super().__init__("Skill is not available.")


class _FaqSkill:
    name: SkillName = "faq"

    def required_fields(self, config: TenantConfig) -> tuple[FieldSpec, ...]:
        del config
        return ()

    def allowed_tools(self, config: TenantConfig) -> frozenset[ToolName]:
        del config
        return frozenset()

    async def route(self, turn: SkillTurn) -> SkillResult:
        del turn
        return SkillResult(kind="deferred")


class _AppointmentsSkill:
    name: SkillName = "appointments"

    def required_fields(self, config: TenantConfig) -> tuple[FieldSpec, ...]:
        del config
        return ()

    def allowed_tools(self, config: TenantConfig) -> frozenset[ToolName]:
        return configured_tool_allowlist(config)

    async def route(self, turn: SkillTurn) -> SkillResult:
        del turn
        return SkillResult(kind="deferred")


class _HandoffSkill:
    name: SkillName = "human_handoff"

    def required_fields(self, config: TenantConfig) -> tuple[FieldSpec, ...]:
        del config
        return ()

    def allowed_tools(self, config: TenantConfig) -> frozenset[ToolName]:
        del config
        return frozenset()

    async def route(self, turn: SkillTurn) -> SkillResult:
        del turn
        return SkillResult(kind="deferred")


class SkillRegistry:
    def __init__(self) -> None:
        self._skills: dict[str, Skill] = {
            "faq": _FaqSkill(),
            "appointments": _AppointmentsSkill(),
            "human_handoff": _HandoffSkill(),
        }

    def resolve(self, name: str, config: TenantConfig) -> Skill:
        if name not in self._skills or name not in config.enabled_skills:
            raise SkillNotAuthorized(name)
        return self._skills[name]
