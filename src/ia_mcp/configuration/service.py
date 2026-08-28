from uuid import UUID

from ia_mcp.configuration.models import (
    TenantAdminContext,
    TenantConfig,
    TenantConfigDraft,
)
from ia_mcp.configuration.ports import ConfigRepository, ConfigurationError
from ia_mcp.tenancy.models import TenantContext, TenantIdentity


class ConfigurationService:
    def __init__(self, repository: ConfigRepository) -> None:
        self._repository = repository

    async def publish(
        self, admin: TenantAdminContext, draft: TenantConfigDraft
    ) -> TenantConfig:
        config = await self._repository.publish(admin, draft)
        await self._repository.record_audit(admin, "publish", int(config.version))
        return config

    async def activate(self, admin: TenantAdminContext, version: int) -> None:
        await self._repository.activate(admin, version)
        await self._repository.record_audit(admin, "activate", version)

    async def capture(
        self, identity: TenantIdentity, correlation_id: UUID
    ) -> tuple[TenantContext, TenantConfig]:
        config = await self._repository.get_active(identity)
        if config is None:
            raise ConfigurationError(
                "not_found",
                "Active configuration is not available.",
            )
        context = TenantContext(
            tenant_id=identity.tenant_id,
            tenant_slug=identity.tenant_slug,
            config_version=int(config.version),
            correlation_id=correlation_id,
        )
        return context, config
