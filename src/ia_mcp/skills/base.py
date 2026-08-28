from dataclasses import dataclass
from typing import Protocol

from ia_mcp.configuration.models import SkillName, TenantConfig
from ia_mcp.mcp.registry import ToolName
from ia_mcp.tenancy.models import TenantContext


@dataclass(frozen=True, slots=True)
class FieldSpec:
    name: str
    required: bool = True


@dataclass(frozen=True, slots=True)
class SkillTurn:
    tenant: TenantContext
    text: str


@dataclass(frozen=True, slots=True)
class SkillResult:
    kind: str


class Skill(Protocol):
    name: SkillName

    def required_fields(self, config: TenantConfig) -> tuple[FieldSpec, ...]: ...

    def allowed_tools(self, config: TenantConfig) -> frozenset[ToolName]: ...

    async def route(self, turn: SkillTurn) -> SkillResult: ...
