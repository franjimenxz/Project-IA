from ia_mcp.tenancy.models import TenantIdentity
from ia_mcp.tenancy.ports import ChannelIntegrationRepository


class TenantResolutionError(Exception):
    def __init__(self, code: str, safe_message: str) -> None:
        self.code = code
        self.safe_message = safe_message
        super().__init__(safe_message)


class TenantService:
    def __init__(self, repository: ChannelIntegrationRepository) -> None:
        self._repository = repository

    async def resolve(self, channel: str, account_id: str) -> TenantIdentity:
        integration = await self._repository.get(channel, account_id)
        if integration is None:
            raise TenantResolutionError(
                "unknown_channel_account",
                "Channel account is not registered.",
            )
        if not integration.enabled:
            raise TenantResolutionError(
                "disabled_channel_account",
                "Channel account is not available.",
            )
        return TenantIdentity(
            tenant_id=integration.tenant_id,
            tenant_slug=integration.tenant_slug,
        )
