from typing import Protocol
from uuid import UUID

from ia_mcp.observability.run_models import RunInvestigation
from ia_mcp.shared.errors import DomainError
from ia_mcp.tenancy.models import TenantContext

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 100
AUDIT_INVESTIGATION_ACTION = "run_investigation_queried"
INVESTIGATION_ACTOR_ID = UUID("00000000-0000-4000-8000-000000000007")


class RunNotFound(DomainError):
    def __init__(self) -> None:
        super().__init__(
            code="not_found",
            safe_message="Resource not found",
            retryable=False,
        )


class RunInvestigationQuery(Protocol):
    async def get(
        self,
        tenant: TenantContext,
        run_id: UUID,
        *,
        tools_cursor: str | None = None,
        tools_limit: int = DEFAULT_PAGE_SIZE,
        events_cursor: str | None = None,
        events_limit: int = DEFAULT_PAGE_SIZE,
    ) -> RunInvestigation: ...


def clamp_page_size(limit: int) -> int:
    if limit < 1:
        return 1
    if limit > MAX_PAGE_SIZE:
        return MAX_PAGE_SIZE
    return limit
