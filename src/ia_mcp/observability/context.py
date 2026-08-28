from collections.abc import Awaitable, Callable
from contextvars import ContextVar, Token
from uuid import UUID, uuid4

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from ia_mcp.observability.propagation import (
    bind_telemetry,
    inject,
    new_server_context,
    reset_telemetry,
    start_span,
)
from ia_mcp.observability.semconv import SPAN_CHANNEL_RECEIVE

CORRELATION_HEADER = "X-Correlation-ID"

_correlation_id: ContextVar[UUID] = ContextVar("ia_mcp_correlation_id")


def current_correlation_id() -> UUID:
    return _correlation_id.get()


def bind_correlation_id(correlation_id: UUID) -> Token[UUID]:
    return _correlation_id.set(correlation_id)


def reset_correlation_id(token: Token[UUID]) -> None:
    _correlation_id.reset(token)


def parse_correlation_id(raw: str | None) -> UUID:
    if raw is None or raw.strip() == "":
        return uuid4()
    try:
        return UUID(raw)
    except ValueError:
        return uuid4()


class CorrelationMiddleware(BaseHTTPMiddleware):
    """Public HTTP boundary: always mint server correlation/trace.

    Unauthenticated callers cannot attach to another tenant's trace by sending
    `traceparent` or `X-Correlation-ID`. Authenticated adapters (e.g. signed
    simulated channel) may adopt a client correlation after verifying the
    caller, independent of this middleware.
    """

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        context = new_server_context()
        request.state.correlation_id = context.correlation_id
        telemetry_token = bind_telemetry(context)
        token = bind_correlation_id(context.correlation_id)
        try:
            with start_span(SPAN_CHANNEL_RECEIVE):
                response = await call_next(request)
                inject(response.headers)
                return response
        finally:
            reset_correlation_id(token)
            reset_telemetry(telemetry_token)
