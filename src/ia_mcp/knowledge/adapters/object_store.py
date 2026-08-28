from uuid import UUID

from ia_mcp.knowledge.ports import KnowledgeError
from ia_mcp.tenancy.models import TenantContext


class InMemoryObjectStore:
    def __init__(self) -> None:
        self._objects: dict[tuple[UUID, str], bytes] = {}

    async def put(self, tenant: TenantContext, key: str, payload: bytes) -> str:
        stored_key = f"{tenant.tenant_id}/{key}"
        self._objects[(tenant.tenant_id, stored_key)] = payload
        return stored_key

    async def get(self, tenant: TenantContext, key: str) -> bytes | None:
        prefix = f"{tenant.tenant_id}/"
        if not key.startswith(prefix):
            raise KnowledgeError(
                "tenant_isolation_violation",
                "Object does not belong to this tenant.",
            )
        return self._objects.get((tenant.tenant_id, key))
