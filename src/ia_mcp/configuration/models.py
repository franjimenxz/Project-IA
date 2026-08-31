from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, PositiveInt, field_validator

from ia_mcp.tenancy.models import TenantIdentity

type SkillName = Literal["faq", "appointments", "human_handoff"]


@dataclass(frozen=True, slots=True)
class TenantAdminContext:
    identity: TenantIdentity
    principal_id: UUID
    roles: frozenset[str]
    correlation_id: UUID


class AgentConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tone: str
    instructions: str | None = Field(default=None, max_length=2000)


class AppointmentPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    credentials_reference: str | None = None
    required_fields: tuple[str, ...] = ()


class KnowledgeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    credentials_reference: str | None = None


class McpConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    credentials_reference: str | None = None


class HandoffPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    credentials_reference: str | None = None


class TenantConfigDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    agent: AgentConfig
    enabled_skills: frozenset[SkillName] = Field(default_factory=frozenset)
    enabled_tools: frozenset[str] = Field(default_factory=frozenset)
    appointments: AppointmentPolicy = Field(default_factory=AppointmentPolicy)
    knowledge: KnowledgeConfig = Field(default_factory=KnowledgeConfig)
    mcp: McpConfig = Field(default_factory=McpConfig)
    handoff: HandoffPolicy = Field(default_factory=HandoffPolicy)
    feature_flags: Mapping[str, bool] = Field(default_factory=dict)

    @field_validator("mcp", "appointments", "knowledge", "handoff")
    @classmethod
    def reject_secret_values(cls, value: BaseModel) -> BaseModel:
        dumped = value.model_dump()
        for key, item in dumped.items():
            if (
                key not in {"credentials_reference"}
                and item not in (None, "", {}, [])
                and ("secret" in key or "password" in key or "token" in key or "api_key" in key)
            ):
                raise ValueError("config must store credential references, not secret values")
        return value


class TenantConfig(TenantConfigDraft):
    model_config = ConfigDict(extra="forbid", frozen=True)
    tenant_id: UUID
    version: PositiveInt
