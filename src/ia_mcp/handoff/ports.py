from typing import Protocol
from uuid import UUID

from ia_mcp.handoff.models import HandoffCase, HandoffDelivery, HandoffOutbox
from ia_mcp.tenancy.models import TenantContext


class HandoffError(Exception):
    def __init__(self, code: str, safe_message: str) -> None:
        self.code = code
        self.safe_message = safe_message
        super().__init__(safe_message)


class HandoffRepository(Protocol):
    async def get(
        self, tenant: TenantContext, handoff_id: UUID
    ) -> HandoffCase | None: ...

    async def get_by_business_key(
        self, tenant: TenantContext, business_key: str
    ) -> HandoffCase | None: ...

    async def create_with_ownership(
        self,
        tenant: TenantContext,
        case: HandoffCase,
        outbox: HandoffOutbox,
        conversation_id: UUID,
    ) -> HandoffCase: ...


class HandoffProvider(Protocol):
    async def transfer(
        self, tenant: TenantContext, payload: HandoffDelivery
    ) -> None: ...
