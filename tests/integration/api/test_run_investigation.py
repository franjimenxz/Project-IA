"""AC-P07-003/004/005: read-only JSON/HTML run investigation with RBAC."""

from __future__ import annotations

from datetime import UTC
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import create_async_engine

from ia_mcp.api.app import create_app
from ia_mcp.observability.adapters.sqlalchemy_run_query import (
    SqlAlchemyRunInvestigationQuery,
)
from ia_mcp.observability.run_models import (
    ConversationSummary,
    RunInvestigation,
    RunSummary,
    TimelineEvent,
    ToolExecutionSummary,
    WorkflowSummary,
)
from ia_mcp.observability.run_query import RunNotFound
from ia_mcp.onboarding.commands import Principal
from ia_mcp.tenancy.models import TenantContext
from tests.fixtures.admin_auth import admin_authenticator, bearer
from tests.integration.observability.test_run_query import (
    CHUNK_TEXT,
    DATABASE_URL,
    MESSAGE_BODY,
    PATIENT_REF,
    PROMPT,
    T_START,
    TENANT_A,
    TENANT_B,
    _reset_schema,
    _seed_tenants_and_channels,
    seed_investigation_fixture,
)

TOKEN = "svctest-run-investigation-token"
MISSING_RUN_ID = UUID("99999999-9999-4999-8999-999999999999")
XSS_SKILL = '<script>alert("xss")</script>'
XSS_ERROR = '<img src=x onerror=alert("err")>'
OPERATOR_A_ID = UUID("aaaaaaaa-0000-4000-8000-0000000000aa")
OPERATOR_B_ID = UUID("bbbbbbbb-0000-4000-8000-0000000000bb")
AUDITOR_A_ID = UUID("aaaaaaaa-0000-4000-8000-0000000000ad")
TENANT_ADMIN_A_ID = UUID("aaaaaaaa-0000-4000-8000-0000000000ae")
TENANT_ADMIN_B_ID = UUID("bbbbbbbb-0000-4000-8000-0000000000ad")


class _ScriptedQuery:
    def __init__(
        self,
        investigation: RunInvestigation | None = None,
        *,
        error: Exception | None = None,
    ) -> None:
        self.investigation = investigation
        self.error = error
        self.calls: list[tuple[TenantContext, UUID, str | None, int, str | None, int]] = []

    async def get(
        self,
        tenant: TenantContext,
        run_id: UUID,
        *,
        tools_cursor: str | None = None,
        tools_limit: int = 50,
        events_cursor: str | None = None,
        events_limit: int = 50,
    ) -> RunInvestigation:
        self.calls.append(
            (tenant, run_id, tools_cursor, tools_limit, events_cursor, events_limit)
        )
        if self.error is not None:
            raise self.error
        if self.investigation is None:
            raise RunNotFound()
        return self.investigation


def _principal(
    *,
    principal_id: UUID,
    roles: frozenset[str],
    tenant_id: UUID | None,
    tenant_slug: str | None,
) -> Principal:
    return Principal(
        principal_id=principal_id,
        roles=roles,
        tenant_id=tenant_id,
        tenant_slug=tenant_slug,
    )


def operator_a() -> Principal:
    return _principal(
        principal_id=OPERATOR_A_ID,
        roles=frozenset({"operator"}),
        tenant_id=TENANT_A,
        tenant_slug="tenant-a",
    )


def operator_b() -> Principal:
    return _principal(
        principal_id=OPERATOR_B_ID,
        roles=frozenset({"operator"}),
        tenant_id=TENANT_B,
        tenant_slug="tenant-b",
    )


def auditor_a() -> Principal:
    return _principal(
        principal_id=AUDITOR_A_ID,
        roles=frozenset({"auditor"}),
        tenant_id=TENANT_A,
        tenant_slug="tenant-a",
    )


def tenant_admin_a() -> Principal:
    return _principal(
        principal_id=TENANT_ADMIN_A_ID,
        roles=frozenset({"tenant_admin"}),
        tenant_id=TENANT_A,
        tenant_slug="tenant-a",
    )


def tenant_admin_b() -> Principal:
    return _principal(
        principal_id=TENANT_ADMIN_B_ID,
        roles=frozenset({"tenant_admin"}),
        tenant_id=TENANT_B,
        tenant_slug="tenant-b",
    )


def _xss_investigation(run_id: UUID) -> RunInvestigation:
    return RunInvestigation(
        run=RunSummary(
            id=run_id,
            conversation_id=uuid4(),
            config_version=1,
            skill=XSS_SKILL,
            workflow_type="create_appointment",
            mcp_server_id="fake-a",
            status="completed",
            error_code=None,
            model_provider=None,
            model_name=None,
            started_at=T_START,
            finished_at=T_START,
            latency_ms=10,
            input_tokens=1,
            output_tokens=1,
            correlation_id=uuid4(),
        ),
        conversation=ConversationSummary(
            id=uuid4(),
            status="active",
            last_message_at=T_START,
            trigger_message_id=uuid4(),
            trigger_direction="inbound",
            trigger_content_type="text",
        ),
        retrievals=(),
        workflow=WorkflowSummary(
            id=uuid4(),
            type="create_appointment",
            state="failed",
            status="failed",
            error=XSS_ERROR,
            schema_version=1,
        ),
        tools=(
            ToolExecutionSummary(
                tool_name="appointments.search",
                mcp_server_id="fake-a",
                status="ok",
                error_code=None,
                occurred_at=T_START,
                retry_count=0,
                sequence=1,
            ),
            ToolExecutionSummary(
                tool_name="appointments.create",
                mcp_server_id="fake-a",
                status="ok",
                error_code=None,
                occurred_at=T_START,
                retry_count=1,
                sequence=2,
            ),
        ),
        handoff=None,
        jobs=(),
        audit_events=(),
        timeline=(
            TimelineEvent(
                occurred_at=T_START,
                kind="run_started",
                label="run started",
                ref=str(run_id),
            ),
        ),
        tools_next_cursor="cursor-tools-2",
        audit_next_cursor="cursor-audit-2",
    )


def make_admin_client(
    *,
    principal: Principal | None = None,
    query: Any = None,
) -> TestClient:
    """A client that presents `TOKEN`, authenticated as `principal`.

    Identity travels in the request, so an anonymous client is one that
    presents no header against a process that declared no principal.
    """
    app = create_app()
    if principal is not None:
        app.state.admin_authenticator = admin_authenticator({TOKEN: principal})
    if query is not None:
        app.state.run_investigation_query = query
    headers = bearer(TOKEN) if principal is not None else {}
    return TestClient(app, headers=headers)


def _error_shape(response: Any) -> tuple[int, str, str]:
    payload = response.json()
    title = str(payload.get("title") or payload.get("code") or "")
    detail = str(payload.get("detail") or "")
    return response.status_code, title, detail


def test_unauthenticated_json_and_html_are_unauthorized() -> None:
    run_id = uuid4()
    client = make_admin_client(query=_ScriptedQuery(_xss_investigation(run_id)))
    json_response = client.get(f"/v1/admin/runs/{run_id}")
    html_response = client.get(f"/admin/runs/{run_id}")
    assert json_response.status_code == 401
    assert html_response.status_code == 401
    assert json_response.json() != {"status": "alive"}


def test_operator_json_returns_run_summary() -> None:
    run_id = uuid4()
    query = _ScriptedQuery(_xss_investigation(run_id))
    client = make_admin_client(principal=operator_a(), query=query)
    response = client.get(f"/v1/admin/runs/{run_id}")
    assert response.status_code == 200
    payload = response.json()
    assert payload["run"]["id"] == str(run_id)
    assert payload["run"]["started_at"].endswith("+00:00") or payload["run"][
        "started_at"
    ].endswith("Z")
    assert query.calls[0][0].tenant_id == TENANT_A
    assert query.calls[0][0].tenant_slug == "tenant-a"


def test_auditor_html_is_read_only_with_visible_utc() -> None:
    run_id = uuid4()
    query = _ScriptedQuery(_xss_investigation(run_id))
    client = make_admin_client(principal=auditor_a(), query=query)
    response = client.get(f"/admin/runs/{run_id}")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    body = response.text
    assert "UTC" in body
    assert "+00:00" in body
    assert T_START.astimezone(UTC).isoformat() in body
    assert "<button" not in body.lower()
    assert 'type="submit"' not in body.lower()
    assert "method=\"post\"" not in body.lower()
    assert XSS_SKILL not in body
    assert XSS_ERROR not in body
    assert "&lt;script&gt;" in body
    assert "<img src=x onerror" not in body.lower()
    assert "&lt;img" in body
    assert "next tools" in body.lower() or "tools_cursor" in body
    assert "audit" in body.lower()


def test_html_pagination_forwards_cursors() -> None:
    run_id = uuid4()
    query = _ScriptedQuery(_xss_investigation(run_id))
    client = make_admin_client(principal=operator_a(), query=query)
    response = client.get(
        f"/admin/runs/{run_id}",
        params={"tools_limit": 1, "events_limit": 1, "tools_cursor": "t0"},
    )
    assert response.status_code == 200
    tenant, called_run, tools_cursor, tools_limit, _events_cursor, events_limit = (
        query.calls[0]
    )
    assert called_run == run_id
    assert tools_cursor == "t0"
    assert tools_limit == 1
    assert events_limit == 1
    assert tenant.tenant_id == TENANT_A
    assert "cursor-tools-2" in response.text


def test_inbound_tenant_header_does_not_bypass_assignment() -> None:
    run_id = uuid4()
    query = _ScriptedQuery(error=RunNotFound())
    client = make_admin_client(principal=operator_b(), query=query)
    response = client.get(
        f"/v1/admin/runs/{run_id}",
        headers={
            "X-Tenant-ID": str(TENANT_A),
            "X-Tenant-Slug": "tenant-a",
        },
    )
    assert response.status_code == 404
    assert query.calls[0][0].tenant_id == TENANT_B
    assert query.calls[0][0].tenant_slug == "tenant-b"


def test_same_tenant_tenant_admin_is_forbidden() -> None:
    """TDD: HTML/JSON view is operator/auditor only, even on the assigned tenant."""
    run_id = uuid4()
    query = _ScriptedQuery(_xss_investigation(run_id))
    client = make_admin_client(principal=tenant_admin_a(), query=query)
    json_response = client.get(f"/v1/admin/runs/{run_id}")
    html_response = client.get(f"/admin/runs/{run_id}")
    assert json_response.status_code == 403
    assert html_response.status_code == 403
    assert query.calls == []


def test_json_and_html_reject_mutations() -> None:
    run_id = uuid4()
    client = make_admin_client(
        principal=operator_a(),
        query=_ScriptedQuery(_xss_investigation(run_id)),
    )
    json_post = client.post(f"/v1/admin/runs/{run_id}", json={"retry": True})
    html_post = client.post(f"/admin/runs/{run_id}", data={"execute": "appointments.search"})
    assert json_post.status_code == 405
    assert html_post.status_code == 405


@pytest.mark.anyio
@pytest.mark.integration
async def test_missing_and_cross_tenant_json_are_uniform_404() -> None:
    _reset_schema()
    _seed_tenants_and_channels()
    engine = create_async_engine(DATABASE_URL)
    try:
        seeded = await seed_investigation_fixture(engine)
        query = SqlAlchemyRunInvestigationQuery(engine)
        client = make_admin_client(principal=operator_a(), query=query)
        missing = client.get(f"/v1/admin/runs/{MISSING_RUN_ID}")
        cross = client.get(f"/v1/admin/runs/{seeded.run_b_id}")
        html_cross = client.get(f"/admin/runs/{seeded.run_b_id}")
        assert _error_shape(missing) == _error_shape(cross)
        assert _error_shape(missing) == (404, "not_found", "Resource not found")
        assert html_cross.status_code == 404
        assert html_cross.json()["detail"] == "Resource not found"
        assert html_cross.json()["title"] == "not_found"
    finally:
        await engine.dispose()


@pytest.mark.anyio
@pytest.mark.integration
async def test_operator_b_cannot_read_run_a() -> None:
    _reset_schema()
    _seed_tenants_and_channels()
    engine = create_async_engine(DATABASE_URL)
    try:
        seeded = await seed_investigation_fixture(engine)
        query = SqlAlchemyRunInvestigationQuery(engine)
        client = make_admin_client(principal=operator_b(), query=query)
        response = client.get(f"/v1/admin/runs/{seeded.run_a_id}")
        html = client.get(f"/admin/runs/{seeded.run_a_id}")
        assert _error_shape(response) == (404, "not_found", "Resource not found")
        assert _error_shape(html) == (404, "not_found", "Resource not found")
    finally:
        await engine.dispose()


@pytest.mark.anyio
@pytest.mark.integration
async def test_tenant_admin_is_forbidden_for_any_run() -> None:
    """tenant_admin is not a view role; same-tenant and foreign both 403."""
    _reset_schema()
    _seed_tenants_and_channels()
    engine = create_async_engine(DATABASE_URL)
    try:
        seeded = await seed_investigation_fixture(engine)
        query = SqlAlchemyRunInvestigationQuery(engine)
        own = make_admin_client(principal=tenant_admin_a(), query=query)
        foreign = make_admin_client(principal=tenant_admin_b(), query=query)
        own_json = own.get(f"/v1/admin/runs/{seeded.run_a_id}")
        own_html = own.get(f"/admin/runs/{seeded.run_a_id}")
        foreign_json = foreign.get(f"/v1/admin/runs/{seeded.run_a_id}")
        assert own_json.status_code == 403
        assert own_html.status_code == 403
        assert foreign_json.status_code == 403
    finally:
        await engine.dispose()


@pytest.mark.anyio
@pytest.mark.integration
async def test_authorized_json_and_html_omit_sensitive_payloads() -> None:
    _reset_schema()
    _seed_tenants_and_channels()
    engine = create_async_engine(DATABASE_URL)
    try:
        seeded = await seed_investigation_fixture(engine)
        query = SqlAlchemyRunInvestigationQuery(engine)
        client = make_admin_client(principal=auditor_a(), query=query)
        json_response = client.get(f"/v1/admin/runs/{seeded.run_a_id}")
        html_response = client.get(
            f"/admin/runs/{seeded.run_a_id}",
            params={"tools_limit": 1, "events_limit": 1},
        )
        assert json_response.status_code == 200
        assert html_response.status_code == 200
        dumped = json_response.text + html_response.text
        assert MESSAGE_BODY not in dumped
        assert CHUNK_TEXT not in dumped
        assert PROMPT not in dumped
        assert PATIENT_REF not in dumped
        assert "30111222" not in dumped
        assert "secret-token" not in dumped
        payload = json_response.json()
        assert payload["run"]["id"] == str(seeded.run_a_id)
        assert payload["run"]["started_at"].startswith("2026-08-28T04:20:00")
        assert "UTC" in html_response.text
        assert "+00:00" in html_response.text
        assert "<button" not in html_response.text.lower()
        assert payload.get("tools_next_cursor") or html_response.text
        assert "appointments.search" in html_response.text or payload["tools"]
    finally:
        await engine.dispose()
