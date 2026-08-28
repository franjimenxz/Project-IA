from uuid import UUID

from ia_mcp.handoff.models import HandoffDelivery
from ia_mcp.handoff.ports import HandoffError
from ia_mcp.tenancy.models import TenantContext


class FakeHandoffAdapter:
    def __init__(self, *, available: bool = True) -> None:
        self.available = available
        self._cases: dict[UUID, list[HandoffDelivery]] = {}

    async def transfer(
        self, tenant: TenantContext, payload: HandoffDelivery
    ) -> None:
        if not self.available:
            raise HandoffError(
                "provider_unavailable", "Handoff provider is unavailable."
            )
        self._cases.setdefault(tenant.tenant_id, []).append(payload)

    def cases_for(self, tenant: TenantContext) -> tuple[HandoffDelivery, ...]:
        return tuple(self._cases.get(tenant.tenant_id, ()))
