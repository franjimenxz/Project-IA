from collections.abc import Callable, MutableSet
from datetime import UTC, datetime
from typing import Annotated, Protocol, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status

from ia_mcp.agent_runtime.harness import AgentHarness
from ia_mcp.channels.models import SimulatedMessageAck, SimulatedMessageRequest
from ia_mcp.channels.outbox import (
    ChannelOutbox,
    OutboundDelivery,
    SimulatedTurnResponse,
)
from ia_mcp.channels.simulated_auth import (
    ACCOUNT_HEADER,
    SIGNATURE_HEADER,
    TIMESTAMP_HEADER,
    SimulatedAuthenticator,
    SimulatedAuthError,
)
from ia_mcp.configuration.ports import ConfigurationError
from ia_mcp.configuration.service import ConfigurationService
from ia_mcp.conversation.models import InboundMessage
from ia_mcp.observability.context import CORRELATION_HEADER, parse_correlation_id
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


def _correlation_id(request: Request) -> UUID:
    state_value = getattr(request.state, "correlation_id", None)
    if isinstance(state_value, UUID):
        return state_value
    return parse_correlation_id(request.headers.get(CORRELATION_HEADER))


@router.post("/v1/simulated/messages", status_code=status.HTTP_202_ACCEPTED)
async def accept_simulated_message(
    request: Request,
    account_id: Annotated[str, Depends(authenticate_simulated)],
    payload: SimulatedMessageRequest,
    tenant_service: Annotated[TenantResolver, Depends(get_tenant_service)],
) -> SimulatedMessageAck | SimulatedTurnResponse:
    try:
        identity = await tenant_service.resolve("simulated", account_id)
    except TenantResolutionError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=exc.safe_message,
        ) from exc
    harness = getattr(request.app.state, "agent_harness", None)
    if not isinstance(harness, AgentHarness):
        return SimulatedMessageAck(tenant_slug=identity.tenant_slug)
    config_service = getattr(request.app.state, "config_service", None)
    outbox = getattr(request.app.state, "outbox", None)
    channel_ids = getattr(request.app.state, "channel_integration_ids", {})
    if not isinstance(config_service, ConfigurationService) or not isinstance(
        outbox, ChannelOutbox
    ):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An internal error occurred",
        )
    integration_id = channel_ids.get(("simulated", account_id))
    if not isinstance(integration_id, UUID):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An internal error occurred",
        )
    try:
        tenant, _config = await config_service.capture(identity, _correlation_id(request))
    except ConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=exc.safe_message,
        ) from exc
    result = await harness.handle_message(
        tenant,
        InboundMessage(
            channel="simulated",
            channel_account_id=account_id,
            channel_integration_id=integration_id,
            external_message_id=payload.external_message_id,
            external_user_id=payload.external_user_id,
            text=payload.text,
            occurred_at=_clock_from(request)(),
        ),
    )
    delivery = await outbox.put(
        OutboundDelivery(
            tenant_id=tenant.tenant_id,
            tenant_slug=tenant.tenant_slug,
            correlation_id=tenant.correlation_id,
            config_version=tenant.config_version,
            run_id=result.run_id,
            kind=result.kind,
            text=result.text,
            source_ids=result.source_ids,
            external_message_id=payload.external_message_id,
        )
    )
    return SimulatedTurnResponse(
        tenant_slug=delivery.tenant_slug,
        kind=delivery.kind,
        text=delivery.text,
        source_ids=delivery.source_ids,
        correlation_id=delivery.correlation_id,
        config_version=delivery.config_version,
        run_id=delivery.run_id,
    )
