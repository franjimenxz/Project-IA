from collections.abc import Awaitable, Callable
from contextvars import ContextVar, Token
from uuid import UUID, uuid4

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

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
    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        correlation_id = parse_correlation_id(request.headers.get(CORRELATION_HEADER))
        request.state.correlation_id = correlation_id
        token = bind_correlation_id(correlation_id)
        try:
            response = await call_next(request)
        finally:
            reset_correlation_id(token)
        response.headers[CORRELATION_HEADER] = str(correlation_id)
        return response
