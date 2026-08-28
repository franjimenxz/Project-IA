from typing import Protocol

from ia_mcp.configuration.models import (
    TenantAdminContext,
    TenantConfig,
    TenantConfigDraft,
)
from ia_mcp.tenancy.models import TenantContext, TenantIdentity


class ConfigRepository(Protocol):
    async def publish(
        self, admin: TenantAdminContext, draft: TenantConfigDraft
    ) -> TenantConfig: ...

    async def activate(self, admin: TenantAdminContext, version: int) -> None: ...

    async def get_active(self, identity: TenantIdentity) -> TenantConfig | None: ...

    async def get_version(self, identity: TenantIdentity, version: int) -> TenantConfig | None: ...

    async def get_for_runtime(self, context: TenantContext) -> TenantConfig | None: ...

    async def record_audit(
        self,
        admin: TenantAdminContext,
        action: str,
        version: int,
    ) -> None: ...


class ConfigurationError(Exception):
    def __init__(self, code: str, safe_message: str) -> None:
        self.code = code
        self.safe_message = safe_message
        super().__init__(safe_message)
