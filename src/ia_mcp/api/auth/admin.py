"""Administrative identity of one request (ADR-007).

The principal is derived from the credentials the caller presented, never from
process state: the authenticator the composition root published is asked to
turn the `Authorization` header into a `Principal`, and a process that
published none authenticates nobody. There is no injection point for an
already-resolved identity, so a test can substitute the authenticator but no
deployment can skip the verification.

Every refusal to authenticate answers 401 with one message: an absent header,
an unparseable one, an unknown token and an unconfigured process must not be
told apart. Authorization failures answer 403 afterwards, which only an
authenticated caller can reach.
"""

from __future__ import annotations

from uuid import UUID, uuid4

from fastapi import HTTPException, Request, status

from ia_mcp.api.auth.service_token import AdminAuthenticator
from ia_mcp.observability.context import current_correlation_id
from ia_mcp.onboarding.commands import Principal
from ia_mcp.tenancy.models import TenantContext

VIEW_ROLES = frozenset({"operator", "auditor"})
AUTHORIZATION_HEADER = "authorization"
_UNAUTHENTICATED = "Administrator identity is required."
_UNAUTHORIZED = "Administrator is not allowed to perform this action."


async def get_principal(request: Request) -> Principal:
    authenticator = getattr(request.app.state, "admin_authenticator", None)
    if not isinstance(authenticator, AdminAuthenticator):
        raise _unauthenticated()
    principal = await authenticator.authenticate(
        request.headers.get(AUTHORIZATION_HEADER)
    )
    if principal is None:
        raise _unauthenticated()
    return principal


async def require_run_investigator(request: Request) -> Principal:
    principal = await get_principal(request)
    if principal.roles.isdisjoint(VIEW_ROLES):
        raise _unauthorized()
    if principal.tenant_id is None or not principal.tenant_slug:
        raise _unauthorized()
    return principal


def tenant_context_for(principal: Principal, request: Request) -> TenantContext:
    if principal.tenant_id is None or not principal.tenant_slug:
        raise _unauthorized()
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


def _unauthenticated() -> HTTPException:
    # The presented credentials are never echoed: a reflected token would leak
    # through logs, proxies and browser history.
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=_UNAUTHENTICATED,
    )


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=_UNAUTHORIZED,
    )
