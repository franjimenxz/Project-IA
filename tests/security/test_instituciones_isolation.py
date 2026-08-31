"""Isolation and auth for the lab HTML surface (AC-P13-007, AC-P13-008).

No PostgreSQL: the onboarding service and harness are stubs so every case is
about identity, tenant context and leakage at the HTTP boundary.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from ia_mcp.agent_runtime.models import AgentTurnResult
from ia_mcp.api.app import create_app
from ia_mcp.configuration.models import AgentConfig, TenantAdminContext, TenantConfig
from ia_mcp.configuration.service import ConfigurationService
from ia_mcp.conversation.models import InboundMessage
from ia_mcp.onboarding.commands import Principal, ProvisionedTenant
from ia_mcp.onboarding.service import PLATFORM_ADMIN, TenantOnboardingService
from ia_mcp.shared.errors import TenantIsolationViolation
from ia_mcp.tenancy.models import TenantContext, TenantIdentity
from tests.fixtures.admin_auth import admin_authenticator, bearer
from tests.fixtures.security_matrix import TENANT_A, TENANT_B

PLATFORM_TOKEN = "svctest-lab-platform-token"
TENANT_A_TOKEN = "svctest-lab-tenant-a-token"
CANARY_B = "canary-b-night-hours-exclusive"
SLUG_A = "tenant-a"
SLUG_B = "tenant-b"
CHANNEL_A = UUID("aa111111-1111-1111-1111-111111111111")
UNAUTHENTICATED = "Administrator identity is required."

PLATFORM = Principal(
    principal_id=UUID("11111111-1111-1111-1111-111111111111"),
    roles=frozenset({PLATFORM_ADMIN}),
)
TENANT_ADMIN_A = Principal(
    principal_id=UUID("44444444-4444-4444-4444-444444444444"),
    roles=frozenset({"tenant_admin"}),
    tenant_id=TENANT_A,
    tenant_slug=SLUG_A,
)


class _IsolationOnboarding(TenantOnboardingService):
    def __init__(self) -> None:
        self.tenants = {
            SLUG_A: ProvisionedTenant(
                identity=TenantIdentity(tenant_id=TENANT_A, tenant_slug=SLUG_A),
                status="active",
                config_version=1,
                config_status="published",
            ),
            SLUG_B: ProvisionedTenant(
                identity=TenantIdentity(tenant_id=TENANT_B, tenant_slug=SLUG_B),
                status="active",
                config_version=1,
                config_status="published",
            ),
        }

    async def get_by_slug(self, slug: str) -> ProvisionedTenant | None:
        return self.tenants.get(slug)

    async def list_tenants(self, principal: Principal) -> tuple[Any, ...]:
        from ia_mcp.onboarding.service import TenantListItem

        items = []
        for slug, tenant in self.tenants.items():
            if PLATFORM_ADMIN in principal.roles:
                pass
            elif (
                principal.tenant_id != tenant.identity.tenant_id
                or principal.tenant_slug != tenant.identity.tenant_slug
            ):
                continue
            items.append(
                TenantListItem(
                    slug=slug,
                    display_name=slug,
                    status=tenant.status,
                    config_version=tenant.config_version,
                )
            )
        return tuple(items)

    async def simulated_channel_id(self, tenant: TenantContext) -> UUID:
        if tenant.tenant_id != TENANT_A:
            raise TenantIsolationViolation()
        return CHANNEL_A


class _IsolationConfig(ConfigurationService):
    async def capture(
        self, identity: TenantIdentity, correlation_id: UUID
    ) -> tuple[TenantContext, TenantConfig]:
        if identity.tenant_id != TENANT_A:
            from ia_mcp.configuration.ports import ConfigurationError

            raise ConfigurationError(
                "not_found",
                "Active configuration is not available.",
            )
        return (
            TenantContext(
                tenant_id=identity.tenant_id,
                tenant_slug=identity.tenant_slug,
                config_version=1,
                correlation_id=correlation_id,
            ),
            TenantConfig(
                tenant_id=identity.tenant_id,
                version=1,
                agent=AgentConfig(tone="formal"),
            ),
        )


class _IsolationHarness:
    async def handle_message(
        self, tenant: TenantContext, message: InboundMessage
    ) -> AgentTurnResult:
        del message
        text = "reply-a"
        if tenant.tenant_id == TENANT_B:
            text = CANARY_B
        return AgentTurnResult(
            kind="insufficient",
            text=text,
            source_ids=(),
            tenant_id=tenant.tenant_id,
            run_id=None,
            trajectory=("receive",),
        )


def _client(*, principal: Principal | None = PLATFORM) -> TestClient:
    app = create_app(environment="test")
    app.state.onboarding_service = _IsolationOnboarding()
    app.state.config_service = _IsolationConfig()
    app.state.agent_harness = _IsolationHarness()
    tokens = {PLATFORM_TOKEN: PLATFORM, TENANT_A_TOKEN: TENANT_ADMIN_A}
    if principal is not None:
        app.state.admin_authenticator = admin_authenticator(tokens)
    return TestClient(app)


@pytest.mark.security
def test_list_of_tenant_a_does_not_reveal_tenant_b() -> None:
    client = _client()
    platform = client.get("/admin/instituciones", headers=bearer(PLATFORM_TOKEN))
    own = client.get("/admin/instituciones", headers=bearer(TENANT_A_TOKEN))
    assert platform.status_code == 200
    assert SLUG_A in platform.text
    # platform_admin may see both; tenant_admin of A must not see B
    assert own.status_code in {200, 403}
    if own.status_code == 200:
        assert SLUG_B not in own.text
        assert CANARY_B not in own.text


@pytest.mark.security
def test_chat_of_a_does_not_include_canary_of_b() -> None:
    client = _client()
    response = client.post(
        f"/admin/instituciones/{SLUG_A}/chat",
        data={"text": "horario", "history": "[]"},
        headers=bearer(PLATFORM_TOKEN),
    )
    assert response.status_code == 200
    assert CANARY_B not in response.text
    assert str(TENANT_B) not in response.text
    assert "reply-a" in response.text


@pytest.mark.security
def test_missing_authorization_is_the_same_401_as_other_admin() -> None:
    client = _client()
    anonymous_list = client.get("/admin/instituciones")
    anonymous_chat = client.get(f"/admin/instituciones/{SLUG_A}/chat")
    anonymous_json = client.get("/v1/admin/tenants")
    for response in (anonymous_list, anonymous_chat, anonymous_json):
        assert response.status_code == 401
        assert response.json()["detail"] == UNAUTHENTICATED


@pytest.mark.security
def test_tenant_admin_of_a_cannot_open_slug_b() -> None:
    client = _client()
    chat = client.get(
        f"/admin/instituciones/{SLUG_B}/chat",
        headers=bearer(TENANT_A_TOKEN),
    )
    post = client.post(
        f"/admin/instituciones/{SLUG_B}/chat",
        data={"text": "hola"},
        headers=bearer(TENANT_A_TOKEN),
    )
    assert chat.status_code == 404
    assert post.status_code == 404
    assert SLUG_B not in chat.text or chat.status_code == 404
    assert CANARY_B not in chat.text
    assert CANARY_B not in post.text


@pytest.mark.security
def test_token_in_form_body_is_not_reflected(
    caplog: pytest.LogCaptureFixture,
) -> None:
    client = _client()
    with caplog.at_level(logging.DEBUG):
        response = client.post(
            "/admin/instituciones",
            data={
                "slug": "clinica-norte",
                "display_name": "Clinica Norte",
                "tone": "formal",
                "mcp_server_id": "fake",
                "mcp_credentials_reference": "sm://clinica-norte/mcp/appointments",
                "token": PLATFORM_TOKEN,
            },
            headers=bearer(PLATFORM_TOKEN),
        )
    rendered = response.text + caplog.text
    assert PLATFORM_TOKEN not in rendered
    assert PLATFORM_TOKEN[:12] not in rendered
    assert TENANT_A_TOKEN not in rendered
