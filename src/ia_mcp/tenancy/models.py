from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class TenantIdentity:
    tenant_id: UUID
    tenant_slug: str


@dataclass(frozen=True, slots=True)
class TenantContext:
    tenant_id: UUID
    tenant_slug: str
    config_version: int
    correlation_id: UUID


@dataclass(frozen=True, slots=True)
class ChannelIntegration:
    tenant_id: UUID
    tenant_slug: str
    enabled: bool
