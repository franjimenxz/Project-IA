from typing import Protocol

from ia_mcp.configuration.models import TenantAdminContext
from ia_mcp.onboarding.commands import Principal, ProvisionedTenant
from ia_mcp.onboarding.models import TenantPackage
from ia_mcp.tenancy.models import ChannelIntegration, TenantIdentity


class TenantOnboardingStore(Protocol):
    async def get_by_slug(self, slug: str) -> ProvisionedTenant | None: ...

    async def provision(
        self, package: TenantPackage, actor: Principal
    ) -> ProvisionedTenant: ...

    async def disable(self, admin: TenantAdminContext, reason: str) -> None: ...

    async def require_active(self, identity: TenantIdentity) -> None: ...

    async def get(self, channel: str, account_id: str) -> ChannelIntegration | None: ...
