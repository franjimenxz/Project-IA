from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from ia_mcp.configuration.models import SkillName


class KnowledgeHit(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    source_id: str
    text: str


class ToolSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    name: str


class ContextRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    skill: SkillName
    history: tuple[str, ...] = ()
    knowledge_hits: tuple[KnowledgeHit, ...] = ()
    workflow_state: str | None = None
    token_budget: int = Field(default=1024, gt=0)


class CompiledContext(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    tenant_id: UUID
    tenant_slug: str
    config_version: int
    correlation_id: UUID
    skill: SkillName
    core_instructions: str
    policies: dict[str, object]
    workflow_state: str | None
    history: tuple[str, ...]
    knowledge: tuple[str, ...]
    tool_schemas: tuple[ToolSchema, ...]
