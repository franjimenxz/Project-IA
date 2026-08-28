from collections.abc import Callable, MutableSet
from datetime import UTC, datetime
from typing import Annotated, Protocol, cast

from fastapi import APIRouter, Depends, HTTPException, Request, status

from ia_mcp.channels.models import SimulatedMessageAck, SimulatedMessageRequest
from ia_mcp.channels.simulated_auth import (
    ACCOUNT_HEADER,
    SIGNATURE_HEADER,
    TIMESTAMP_HEADER,
    SimulatedAuthenticator,
    SimulatedAuthError,
)
from ia_mcp.tenancy.models import TenantIdentity
from ia_mcp.tenancy.service import TenantResolutionError


class TenantResolver(Protocol):
    async def resolve(self, channel: str, account_id: str) -> TenantIdentity: ...


router = APIRouter()


def _clock_from(request: Request) -> Callable[[], datetime]:
    clock = getattr(request.app.state, "simulated_clock", None)
    if callable(clock):
        return cast(Callable[[], datetime], clock)
    return lambda: datetime.now(UTC)


def _authenticator(request: Request) -> SimulatedAuthenticator:
    store = getattr(request.app.state, "simulated_replay_store", None)
    if store is None:
        replay_store: set[str] = set()
        request.app.state.simulated_replay_store = replay_store
    else:
        replay_store = cast(set[str], store)
    return SimulatedAuthenticator(
        clock=_clock_from(request),
        replay_store=cast(MutableSet[str], replay_store),
    )


async def authenticate_simulated(request: Request) -> str:
    authenticator = _authenticator(request)
    try:
        return authenticator.authenticate(
            account=request.headers.get(ACCOUNT_HEADER),
            timestamp=request.headers.get(TIMESTAMP_HEADER),
            signature=request.headers.get(SIGNATURE_HEADER),
            body=await request.body(),
        )
    except SimulatedAuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=exc.safe_message,
        ) from exc


def get_tenant_service(request: Request) -> TenantResolver:
    service = getattr(request.app.state, "tenant_service", None)
    if service is None or not hasattr(service, "resolve"):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An internal error occurred",
        )
    return cast(TenantResolver, service)


@router.post("/v1/simulated/messages", status_code=status.HTTP_202_ACCEPTED)
async def accept_simulated_message(
    account_id: Annotated[str, Depends(authenticate_simulated)],
    payload: SimulatedMessageRequest,
    tenant_service: Annotated[TenantResolver, Depends(get_tenant_service)],
) -> SimulatedMessageAck:
    del payload
    try:
        identity = await tenant_service.resolve("simulated", account_id)
    except TenantResolutionError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=exc.safe_message,
        ) from exc
    return SimulatedMessageAck(tenant_slug=identity.tenant_slug)
