import json
import logging
from collections.abc import Mapping
from typing import Any
from uuid import UUID, uuid4

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from ia_mcp.observability.context import CORRELATION_HEADER, current_correlation_id
from ia_mcp.observability.redaction import redact
from ia_mcp.shared.errors import DomainError, TenantIsolationViolation

logger = logging.getLogger("ia_mcp.api.errors")


def _status_for(exc: DomainError) -> int:
    if isinstance(exc, TenantIsolationViolation):
        return 404
    if exc.retryable:
        return 503
    return 400


def _correlation_id_for(request: Request) -> UUID:
    state_value = getattr(request.state, "correlation_id", None)
    if isinstance(state_value, UUID):
        return state_value
    try:
        return current_correlation_id()
    except LookupError:
        return uuid4()


def _problem(status: int, title: str, detail: str, correlation_id: UUID) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={
            "type": "about:blank",
            "title": title,
            "status": status,
            "detail": detail,
            "correlation_id": str(correlation_id),
        },
        media_type="application/problem+json",
        headers={CORRELATION_HEADER: str(correlation_id)},
    )


def _redact_details(details: Mapping[str, Any]) -> str:
    return redact(json.dumps(details, default=str))


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(DomainError)
    async def domain_error_handler(request: Request, exc: DomainError) -> JSONResponse:
        correlation_id = _correlation_id_for(request)
        logger.error(
            "domain_error code=%s retryable=%s correlation_id=%s details=%s",
            redact(exc.code),
            exc.retryable,
            correlation_id,
            _redact_details(exc.details),
        )
        return _problem(_status_for(exc), exc.code, exc.safe_message, correlation_id)

    @app.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
        correlation_id = _correlation_id_for(request)
        logger.error(
            "unhandled_error correlation_id=%s %s",
            correlation_id,
            redact(f"{type(exc).__name__}: {exc}"),
        )
        return _problem(500, "internal_error", "An internal error occurred", correlation_id)
