from __future__ import annotations

from uuid import UUID, uuid4

from fastapi import HTTPException, Request, status

from ia_mcp.observability.context import current_correlation_id
from ia_mcp.onboarding.commands import Principal
from ia_mcp.tenancy.models import TenantContext

VIEW_ROLES = frozenset({"operator", "auditor"})


def get_principal(request: Request) -> Principal:
    principal = getattr(request.app.state, "principal", None)
    if not isinstance(principal, Principal):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Administrator identity is required.",
        )
    return principal


def require_run_investigator(request: Request) -> Principal:
    principal = get_principal(request)
    if principal.roles.isdisjoint(VIEW_ROLES):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator is not allowed to perform this action.",
        )
    if principal.tenant_id is None or not principal.tenant_slug:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator is not allowed to perform this action.",
        )
    return principal


def tenant_context_for(principal: Principal, request: Request) -> TenantContext:
    if principal.tenant_id is None or not principal.tenant_slug:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator is not allowed to perform this action.",
        )
    correlation = getattr(request.state, "correlation_id", None)
    if not isinstance(correlation, UUID):
        try:
            correlation = current_correlation_id()
        except LookupError:
            correlation = uuid4()
    return TenantContext(
        tenant_id=principal.tenant_id,
        tenant_slug=principal.tenant_slug,
        config_version=1,
        correlation_id=correlation,
    )
