from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, PositiveInt, StringConstraints

from ia_mcp.configuration.models import AgentConfig, SkillName

NonEmptyStr = Annotated[str, StringConstraints(min_length=1, strip_whitespace=True)]
PACKAGE_SCHEMA_VERSION: Literal[1] = 1
CHANNEL_NAME = Literal["simulated", "whatsapp"]
INTEGRATION_KIND = Literal["mcp", "channel", "handoff", "storage"]


class ValidationIssue(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    path: str
    code: str
    message: str


class ValidationReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    valid: bool
    schema_version: Literal[1] = PACKAGE_SCHEMA_VERSION
    package_path: str
    content_hash: str | None = None
    errors: tuple[ValidationIssue, ...] = ()
    warnings: tuple[ValidationIssue, ...] = ()


class TenantDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]
    slug: Annotated[str, StringConstraints(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")]
    display_name: NonEmptyStr


class PackageAppointmentPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    required_fields: tuple[str, ...] = ()
    credentials_reference: str | None = None


class PackageKnowledgeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    namespace: NonEmptyStr
    credentials_reference: str | None = None


class PackageMcpConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    server_id: NonEmptyStr
    credentials_reference: str | None = None


class PackageHandoffPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    credentials_reference: str | None = None


class PackageConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]
    version: PositiveInt
    agent: AgentConfig
    enabled_skills: tuple[SkillName, ...]
    enabled_tools: tuple[str, ...] = ()
    appointments: PackageAppointmentPolicy = Field(
        default_factory=PackageAppointmentPolicy
    )
    knowledge: PackageKnowledgeConfig
    mcp: PackageMcpConfig
    handoff: PackageHandoffPolicy = Field(default_factory=PackageHandoffPolicy)
    feature_flags: Mapping[str, bool] = Field(default_factory=dict)


class ChannelBinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    channel: CHANNEL_NAME
    external_account_id: NonEmptyStr
    secret_reference: NonEmptyStr


class IntegrationBinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: INTEGRATION_KIND
    server_id: NonEmptyStr | None = None
    credentials_reference: NonEmptyStr
    capabilities: tuple[str, ...] = ()


class IntegrationsDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]
    channels: tuple[ChannelBinding, ...]
    integrations: tuple[IntegrationBinding, ...] = ()


class KnowledgeDocumentRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    logical_name: NonEmptyStr
    source: Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9+.-]*://\S+$")]
    checksum: Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]
    mime_type: NonEmptyStr


class KnowledgeManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]
    namespace: NonEmptyStr
    documents: tuple[KnowledgeDocumentRef, ...] = ()


class PolicyDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]
    skill: SkillName


class PackageEvalMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["user", "assistant"]
    text: NonEmptyStr


class PackageEvalCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: NonEmptyStr
    tenant_fixture: NonEmptyStr
    config_version: PositiveInt = 1
    expected_skill: SkillName
    allowed_tools: tuple[str, ...] = ()
    forbidden_tools: tuple[str, ...] = ()
    messages: tuple[PackageEvalMessage, ...] = ()


class TenantPackage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant: TenantDocument
    config: PackageConfig
    policies: tuple[PolicyDocument, ...]
    knowledge: KnowledgeManifest
    integrations: IntegrationsDocument
    evals: tuple[PackageEvalCase, ...]
