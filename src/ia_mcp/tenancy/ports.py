from typing import Protocol

from ia_mcp.tenancy.models import ChannelIntegration


class ChannelIntegrationRepository(Protocol):
    async def get(self, channel: str, account_id: str) -> ChannelIntegration | None: ...
