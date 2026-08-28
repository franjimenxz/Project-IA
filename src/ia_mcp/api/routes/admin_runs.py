from __future__ import annotations

from datetime import UTC, datetime
from html import escape
from pathlib import Path
from string import Template
from typing import Annotated, cast
from urllib.parse import urlencode
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse

from ia_mcp.api.auth.admin import require_run_investigator, tenant_context_for
from ia_mcp.observability.context import CORRELATION_HEADER, current_correlation_id
from ia_mcp.observability.run_models import RunInvestigation
from ia_mcp.observability.run_query import (
    DEFAULT_PAGE_SIZE,
    InvalidCursor,
    RunInvestigationQuery,
    RunNotFound,
)
from ia_mcp.onboarding.commands import Principal

_TEMPLATE_PATH = (
    Path(__file__).resolve().parent.parent / "templates" / "run_investigation.html"
)


def create_admin_runs_router() -> APIRouter:
    router = APIRouter()

    @router.get("/v1/admin/runs/{run_id}")
    async def get_run_json(
        run_id: UUID,
        request: Request,
        principal: Annotated[Principal, Depends(require_run_investigator)],
        tools_cursor: str | None = None,
        tools_limit: int = DEFAULT_PAGE_SIZE,
        events_cursor: str | None = None,
        events_limit: int = DEFAULT_PAGE_SIZE,
    ) -> JSONResponse:
        try:
            investigation = await _fetch_investigation(
                request,
                principal,
                run_id,
                tools_cursor=tools_cursor,
                tools_limit=tools_limit,
                events_cursor=events_cursor,
                events_limit=events_limit,
            )
        except RunNotFound:
            return _not_found_response(request)
        return JSONResponse(content=investigation.model_dump(mode="json"))

    @router.get("/admin/runs/{run_id}", response_model=None)
    async def get_run_html(
        run_id: UUID,
        request: Request,
        principal: Annotated[Principal, Depends(require_run_investigator)],
        tools_cursor: str | None = None,
        tools_limit: int = DEFAULT_PAGE_SIZE,
        events_cursor: str | None = None,
        events_limit: int = DEFAULT_PAGE_SIZE,
    ) -> HTMLResponse | JSONResponse:
        try:
            investigation = await _fetch_investigation(
                request,
                principal,
                run_id,
                tools_cursor=tools_cursor,
                tools_limit=tools_limit,
                events_cursor=events_cursor,
                events_limit=events_limit,
            )
        except RunNotFound:
            return _not_found_response(request)
        return HTMLResponse(
            content=_render_html(
                investigation,
                tools_limit=tools_limit,
                events_limit=events_limit,
            )
        )

    return router


def _get_query(request: Request) -> RunInvestigationQuery:
    query = getattr(request.app.state, "run_investigation_query", None)
    if query is None or not hasattr(query, "get"):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An internal error occurred",
        )
    return cast(RunInvestigationQuery, query)


async def _fetch_investigation(
    request: Request,
    principal: Principal,
    run_id: UUID,
    *,
    tools_cursor: str | None,
    tools_limit: int,
    events_cursor: str | None,
    events_limit: int,
) -> RunInvestigation:
    query = _get_query(request)
    tenant = tenant_context_for(principal, request)
    try:
        return await query.get(
            tenant,
            run_id,
            tools_cursor=tools_cursor,
            tools_limit=tools_limit,
            events_cursor=events_cursor,
            events_limit=events_limit,
        )
    except InvalidCursor as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=exc.safe_message,
        ) from exc


def _not_found_response(request: Request) -> JSONResponse:
    correlation = getattr(request.state, "correlation_id", None)
    if not isinstance(correlation, UUID):
        try:
            correlation = current_correlation_id()
        except LookupError:
            correlation = None
    payload: dict[str, object] = {
        "type": "about:blank",
        "title": "not_found",
        "status": 404,
        "detail": "Resource not found",
    }
    headers: dict[str, str] = {}
    if correlation is not None:
        payload["correlation_id"] = str(correlation)
        headers[CORRELATION_HEADER] = str(correlation)
    return JSONResponse(
        status_code=status.HTTP_404_NOT_FOUND,
        content=payload,
        media_type="application/problem+json",
        headers=headers,
    )


def _utc(value: datetime | None) -> str:
    if value is None:
        return ""
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()


def _cell(value: object) -> str:
    if value is None:
        return ""
    return escape(str(value), quote=True)


def _row(cells: list[object]) -> str:
    inner = "".join(f"<td>{_cell(item)}</td>" for item in cells)
    return f"<tr>{inner}</tr>"


def _pagination(
    *,
    run_id: UUID,
    rel: str,
    cursor: str | None,
    tools_limit: int,
    events_limit: int,
    cursor_key: str,
) -> str:
    if cursor is None:
        return ""
    query = urlencode(
        {
            cursor_key: cursor,
            "tools_limit": tools_limit,
            "events_limit": events_limit,
        }
    )
    href = escape(f"/admin/runs/{run_id}?{query}", quote=True)
    label = escape(rel, quote=True)
    return f'<p class="pagination"><a href="{href}">{label}</a></p>'


def _render_html(
    investigation: RunInvestigation,
    *,
    tools_limit: int,
    events_limit: int,
) -> str:
    run = investigation.run
    conversation = investigation.conversation
    workflow = investigation.workflow
    handoff = investigation.handoff
    if workflow is None:
        workflow_block = "<p>None</p>"
    else:
        workflow_block = (
            "<dl>"
            f"<dt>type</dt><dd>{_cell(workflow.type)}</dd>"
            f"<dt>state</dt><dd>{_cell(workflow.state)}</dd>"
            f"<dt>status</dt><dd>{_cell(workflow.status)}</dd>"
            f"<dt>error</dt><dd>{_cell(workflow.error)}</dd>"
            "</dl>"
        )
    if handoff is None:
        handoff_block = "<p>None</p>"
    else:
        handoff_block = (
            "<dl>"
            f"<dt>status</dt><dd>{_cell(handoff.status)}</dd>"
            f"<dt>reason</dt><dd>{_cell(handoff.reason)}</dd>"
            f"<dt>requested at (UTC)</dt><dd>{_cell(_utc(handoff.requested_at))}</dd>"
            "</dl>"
        )
    if investigation.trace_url is None:
        trace_block = "<p>No trace link</p>"
    else:
        href = escape(str(investigation.trace_url), quote=True)
        trace_block = f'<p><a href="{href}">Trace</a></p>'
    template = Template(_TEMPLATE_PATH.read_text(encoding="utf-8"))
    return template.safe_substitute(
        run_id=_cell(run.id),
        status=_cell(run.status),
        skill=_cell(run.skill),
        workflow_type=_cell(run.workflow_type),
        mcp_server_id=_cell(run.mcp_server_id),
        started_at=_cell(_utc(run.started_at)),
        finished_at=_cell(_utc(run.finished_at)),
        error_code=_cell(run.error_code),
        latency_ms=_cell(run.latency_ms),
        conversation_id=_cell(conversation.id),
        conversation_status=_cell(conversation.status),
        last_message_at=_cell(_utc(conversation.last_message_at)),
        trigger_direction=_cell(conversation.trigger_direction),
        trigger_content_type=_cell(conversation.trigger_content_type),
        workflow_block=workflow_block,
        timeline_rows="".join(
            _row([_utc(item.occurred_at), item.kind, item.label, item.error_code])
            for item in investigation.timeline
        ),
        retrievals_rows="".join(
            _row([item.source_id, _utc(item.occurred_at)])
            for item in investigation.retrievals
        ),
        tools_rows="".join(
            _row(
                [
                    item.tool_name,
                    item.status,
                    _utc(item.occurred_at),
                    item.retry_count,
                ]
            )
            for item in investigation.tools
        ),
        tools_pagination=_pagination(
            run_id=run.id,
            rel="Next tools",
            cursor=investigation.tools_next_cursor,
            tools_limit=tools_limit,
            events_limit=events_limit,
            cursor_key="tools_cursor",
        ),
        jobs_rows="".join(
            _row(
                [
                    item.type,
                    item.status,
                    item.attempts,
                    _utc(item.scheduled_for),
                    item.last_error,
                ]
            )
            for item in investigation.jobs
        ),
        handoff_block=handoff_block,
        audit_rows="".join(
            _row([item.action, _utc(item.created_at), item.version])
            for item in investigation.audit_events
        ),
        audit_pagination=_pagination(
            run_id=run.id,
            rel="Next audit",
            cursor=investigation.audit_next_cursor,
            tools_limit=tools_limit,
            events_limit=events_limit,
            cursor_key="events_cursor",
        ),
        trace_block=trace_block,
    )
