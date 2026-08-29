"""Negative matrix for administrative authentication (ADR-007).

No PostgreSQL: the onboarding service is a stub and the run investigation query
is scripted, so every case here is about identity, role and leakage at the HTTP
boundary — not about what the stores hold.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from ia_mcp.api.app import create_app
from ia_mcp.configuration.models import TenantAdminContext
from ia_mcp.observability.context import CORRELATION_HEADER
from ia_mcp.observability.run_models import (
    ConversationSummary,
    RunInvestigation,
    RunSummary,
)
from ia_mcp.observability.run_query import RunNotFound
from ia_mcp.onboarding.commands import Principal, ProvisionedTenant
from ia_mcp.onboarding.service import TenantOnboardingService
from ia_mcp.tenancy.models import TenantContext, TenantIdentity
from tests.fixtures.admin_auth import admin_authenticator, bearer
from tests.fixtures.security_matrix import (
    OCCURRED_AT,
    TENANT_A,
    TENANT_A_IDENTITY,
    TENANT_B,
)

RUN_ID = UUID("aa444444-4444-4444-4444-444444444444")
# Canary tokens. Each one is a value no legitimate response may contain, so a
# leak is detectable even from a fragment.
PLATFORM_TOKEN = "svctest-platform-admin-token"
OPERATOR_A_TOKEN = "svctest-operator-alpha-token"
OPERATOR_B_TOKEN = "svctest-operator-bravo-token"
TENANT_ADMIN_TOKEN = "svctest-tenant-admin-token"
# One character apart from a valid token: a prefix comparison would accept it.
WRONG_TOKEN = "svctest-operator-alpha-tokes"
REPORT_HASH = "0" * 64

PLATFORM = Principal(
    principal_id=UUID("11111111-1111-1111-1111-111111111111"),
    roles=frozenset({"platform_admin"}),
)
OPERATOR_A = Principal(
    principal_id=UUID("22222222-2222-2222-2222-222222222222"),
    roles=frozenset({"operator"}),
    tenant_id=TENANT_A,
    tenant_slug="tenant-a",
)
OPERATOR_B = Principal(
    principal_id=UUID("33333333-3333-3333-3333-333333333333"),
    roles=frozenset({"operator"}),
    tenant_id=TENANT_B,
    tenant_slug="tenant-b",
)
TENANT_ADMIN_A = Principal(
    principal_id=UUID("44444444-4444-4444-4444-444444444444"),
    roles=frozenset({"tenant_admin"}),
    tenant_id=TENANT_A,
    tenant_slug="tenant-a",
)

TOKENS = {
    PLATFORM_TOKEN: PLATFORM,
    OPERATOR_A_TOKEN: OPERATOR_A,
    OPERATOR_B_TOKEN: OPERATOR_B,
    TENANT_ADMIN_TOKEN: TENANT_ADMIN_A,
}

ADMIN_REQUESTS: tuple[tuple[str, str, dict[str, Any] | None], ...] = (
    ("GET", f"/v1/admin/runs/{RUN_ID}", None),
    ("GET", f"/admin/runs/{RUN_ID}", None),
    ("POST", "/v1/admin/tenants/provision", {"package_path": "b"}),
    ("GET", "/v1/admin/tenants/tenant-a", None),
    ("POST", "/v1/admin/tenants/tenant-a/disable", {"reason": "cutover"}),
    ("POST", "/v1/admin/tenants/tenant-a/preflight", {"package_path": "b"}),
    ("POST", "/v1/admin/tenants/tenant-a/activate", {"report_hash": REPORT_HASH}),
)


class _TenantARunQuery:
    """Answers for tenant A only, the way a tenant-scoped store would."""

    def __init__(self) -> None:
        self.tenants: list[TenantContext] = []

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
        self.tenants.append(tenant)
        if tenant.tenant_id != TENANT_A:
            raise RunNotFound()
        return RunInvestigation(
            run=RunSummary(
                id=run_id,
                conversation_id=uuid4(),
                config_version=1,
                skill="faq",
                workflow_type=None,
                mcp_server_id=None,
                status="succeeded",
                error_code=None,
                model_provider=None,
                model_name=None,
                started_at=OCCURRED_AT,
                finished_at=OCCURRED_AT,
                latency_ms=1,
                input_tokens=1,
                output_tokens=1,
                correlation_id=uuid4(),
            ),
            conversation=ConversationSummary(
                id=uuid4(),
                status="bot_owned",
                last_message_at=OCCURRED_AT,
                trigger_message_id=uuid4(),
                trigger_direction="inbound",
                trigger_content_type="text",
            ),
            retrievals=(),
            workflow=None,
            tools=(),
            handoff=None,
            jobs=(),
            audit_events=(),
            timeline=(),
        )


class _StubOnboardingService(TenantOnboardingService):
    """Records what crossed the boundary; never opens a database session."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def get_by_slug(self, slug: str) -> ProvisionedTenant | None:
        self.calls.append(f"get:{slug}")
        return ProvisionedTenant(
            identity=TenantIdentity(tenant_id=TENANT_A, tenant_slug=slug),
            status="disabled",
            config_version=1,
            config_status="draft",
        )

    async def disable(self, admin: TenantAdminContext, reason: str) -> None:
        self.calls.append(f"disable:{admin.identity.tenant_slug}")

    async def activate(self, admin: TenantAdminContext, report_hash: str) -> None:
        self.calls.append(f"activate:{admin.identity.tenant_slug}")


def _client(
    *,
    authenticated: bool = True,
    published_principal: Principal | None = None,
) -> tuple[TestClient, _TenantARunQuery, _StubOnboardingService]:
    app = create_app(environment="test")
    query = _TenantARunQuery()
    service = _StubOnboardingService()
    app.state.run_investigation_query = query
    app.state.onboarding_service = service
    if authenticated:
        app.state.admin_authenticator = admin_authenticator(TOKENS)
    if published_principal is not None:
        app.state.principal = published_principal
    return TestClient(app), query, service


def _call(
    client: TestClient,
    method: str,
    path: str,
    body: dict[str, Any] | None,
    headers: dict[str, str] | None = None,
) -> Any:
    return client.request(method, path, json=body, headers=headers)


def _shape(response: Any) -> tuple[int, str]:
    return response.status_code, response.text


@pytest.mark.security
def test_every_admin_route_refuses_a_caller_without_a_token() -> None:
    client, query, service = _client()
    for method, path, body in ADMIN_REQUESTS:
        response = _call(client, method, path, body)
        assert response.status_code == 401, path
    assert query.tenants == []
    assert service.calls == []


@pytest.mark.security
def test_an_invalid_token_is_indistinguishable_from_an_absent_one() -> None:
    client, query, service = _client()
    for method, path, body in ADMIN_REQUESTS:
        anonymous = _call(client, method, path, body)
        invalid = _call(client, method, path, body, bearer(WRONG_TOKEN))
        malformed = _call(client, method, path, body, {"Authorization": WRONG_TOKEN})
        assert _shape(invalid) == _shape(anonymous), path
        assert _shape(malformed) == _shape(anonymous), path
        assert set(invalid.headers) - {CORRELATION_HEADER} == (
            set(anonymous.headers) - {CORRELATION_HEADER}
        )
    assert query.tenants == []
    assert service.calls == []


@pytest.mark.security
def test_a_published_principal_is_never_an_authentication_bypass() -> None:
    """`app.state.principal` was the old identity; it must open nothing now."""
    client, query, service = _client(authenticated=False, published_principal=PLATFORM)
    for method, path, body in ADMIN_REQUESTS:
        assert _call(client, method, path, body).status_code == 401, path
        assert _call(
            client, method, path, body, bearer(PLATFORM_TOKEN)
        ).status_code == 401, path
    assert query.tenants == []
    assert service.calls == []


@pytest.mark.security
def test_a_published_principal_does_not_outrank_the_presented_token() -> None:
    """With an authenticator wired, the token decides and the state is ignored."""
    client, _, service = _client(published_principal=PLATFORM)
    denied = _call(
        client,
        "POST",
        "/v1/admin/tenants/provision",
        {"package_path": "b"},
        bearer(OPERATOR_A_TOKEN),
    )
    assert denied.status_code == 403
    assert service.calls == []


@pytest.mark.security
def test_an_authenticated_token_without_the_role_is_forbidden() -> None:
    client, query, service = _client()
    provision = _call(
        client,
        "POST",
        "/v1/admin/tenants/provision",
        {"package_path": "b"},
        bearer(OPERATOR_A_TOKEN),
    )
    run_json = _call(client, "GET", f"/v1/admin/runs/{RUN_ID}", None, bearer(TENANT_ADMIN_TOKEN))
    run_html = _call(client, "GET", f"/admin/runs/{RUN_ID}", None, bearer(TENANT_ADMIN_TOKEN))
    platform_run = _call(client, "GET", f"/v1/admin/runs/{RUN_ID}", None, bearer(PLATFORM_TOKEN))
    assert provision.status_code == 403
    assert run_json.status_code == 403
    assert run_html.status_code == 403
    # `platform_admin` carries no tenant, so it is not a run investigator either.
    assert platform_run.status_code == 403
    assert query.tenants == []
    assert service.calls == []


@pytest.mark.security
def test_a_token_from_another_tenant_never_reads_a_foreign_run() -> None:
    client, query, _ = _client()
    own = _call(client, "GET", f"/v1/admin/runs/{RUN_ID}", None, bearer(OPERATOR_A_TOKEN))
    foreign = _call(client, "GET", f"/v1/admin/runs/{RUN_ID}", None, bearer(OPERATOR_B_TOKEN))
    spoofed = _call(
        client,
        "GET",
        f"/v1/admin/runs/{RUN_ID}",
        None,
        bearer(OPERATOR_B_TOKEN) | {"X-Tenant-ID": str(TENANT_A), "X-Tenant-Slug": "tenant-a"},
    )
    assert own.status_code == 200
    assert foreign.status_code == 404
    assert spoofed.status_code == 404
    assert [item.tenant_id for item in query.tenants] == [TENANT_A, TENANT_B, TENANT_B]
    assert TENANT_A_IDENTITY.tenant_slug not in foreign.text


@pytest.mark.security
def test_no_response_or_log_carries_the_token_or_the_secret(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """AC: no fragment of a presented or declared token may escape."""
    client, _, _ = _client()
    bodies: list[str] = []
    with caplog.at_level(logging.DEBUG):
        for method, path, body in ADMIN_REQUESTS:
            for headers in (
                None,
                bearer(WRONG_TOKEN),
                bearer(OPERATOR_A_TOKEN),
                bearer(PLATFORM_TOKEN),
                {"Authorization": f"Bearer {PLATFORM_TOKEN}"},
            ):
                response = _call(client, method, path, body, headers)
                bodies.append(response.text)
                bodies.extend(f"{name}: {value}" for name, value in response.headers.items())
    rendered = "".join(bodies) + caplog.text
    for token in (*TOKENS, WRONG_TOKEN):
        assert token not in rendered
        assert token[:12] not in rendered
