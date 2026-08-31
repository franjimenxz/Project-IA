"""HTML lab pages for institutions (AC-P13-004, AC-P13-005, AC-P13-006).

No PostgreSQL: collaborators are stubs. The suite checks routes, form fields,
provision/lab_enable wiring and that chat calls the harness with the slug's
TenantContext — not the simulated-channel signature.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from ia_mcp.agent_runtime.models import AgentTurnResult
from ia_mcp.api.app import create_app
from ia_mcp.configuration.models import (
    AgentConfig,
    TenantAdminContext,
    TenantConfig,
    TenantConfigDraft,
)
from ia_mcp.configuration.service import ConfigurationService
from ia_mcp.conversation.models import InboundMessage
from ia_mcp.onboarding.commands import Principal, ProvisionedTenant
from ia_mcp.onboarding.models import TenantPackage
from ia_mcp.onboarding.service import PLATFORM_ADMIN, TenantOnboardingService
from ia_mcp.tenancy.models import TenantContext, TenantIdentity
from tests.fixtures.admin_auth import admin_authenticator, bearer

TOKEN = "svctest-instituciones-html-token"
TENANT_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
CHANNEL_ID = UUID("aa111111-1111-1111-1111-111111111111")
SLUG = "clinica-norte"

PLATFORM = Principal(
    principal_id=UUID("11111111-1111-1111-1111-111111111111"),
    roles=frozenset({PLATFORM_ADMIN}),
)


def _provisioned(slug: str = SLUG) -> ProvisionedTenant:
    return ProvisionedTenant(
        identity=TenantIdentity(tenant_id=TENANT_ID, tenant_slug=slug),
        status="active",
        config_version=1,
        config_status="published",
    )


class StubOnboardingService(TenantOnboardingService):
    """Records lab mutations; never opens a database session."""

    def __init__(self) -> None:
        self.provisioned: list[TenantPackage] = []
        self.lab_enabled: list[str] = []
        self.tenants: dict[str, ProvisionedTenant] = {SLUG: _provisioned()}
        self.channel_lookups: list[TenantContext] = []

    async def get_by_slug(self, slug: str) -> ProvisionedTenant | None:
        return self.tenants.get(slug)

    async def provision(
        self, package: TenantPackage, actor: Principal
    ) -> ProvisionedTenant:
        del actor
        self.provisioned.append(package)
        tenant = _provisioned(package.tenant.slug)
        self.tenants[package.tenant.slug] = tenant
        return tenant

    async def lab_enable(self, admin: TenantAdminContext) -> ProvisionedTenant:
        self.lab_enabled.append(admin.identity.tenant_slug)
        tenant = _provisioned(admin.identity.tenant_slug)
        self.tenants[admin.identity.tenant_slug] = tenant
        return tenant

    async def list_tenants(self, principal: Principal) -> tuple[Any, ...]:
        from ia_mcp.onboarding.service import TenantListItem

        del principal
        return (
            TenantListItem(
                slug=SLUG,
                display_name="Clinica Norte",
                status="active",
                config_version=1,
            ),
        )

    async def simulated_channel_id(self, tenant: TenantContext) -> UUID:
        self.channel_lookups.append(tenant)
        return CHANNEL_ID


class StubConfigService(ConfigurationService):
    def __init__(self) -> None:
        self.captures: list[TenantIdentity] = []
        self.published: list[TenantConfigDraft] = []

    async def capture(
        self, identity: TenantIdentity, correlation_id: UUID
    ) -> tuple[TenantContext, TenantConfig]:
        self.captures.append(identity)
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

    async def publish(
        self, admin: TenantAdminContext, draft: TenantConfigDraft
    ) -> TenantConfig:
        self.published.append(draft)
        return TenantConfig(
            tenant_id=admin.identity.tenant_id,
            version=2,
            agent=draft.agent,
            enabled_skills=draft.enabled_skills,
            enabled_tools=draft.enabled_tools,
        )


class StubHarness:
    def __init__(self) -> None:
        self.messages: list[tuple[TenantContext, InboundMessage]] = []

    async def handle_message(
        self, tenant: TenantContext, message: InboundMessage
    ) -> AgentTurnResult:
        self.messages.append((tenant, message))
        return AgentTurnResult(
            kind="insufficient",
            text="lab-reply",
            source_ids=(),
            tenant_id=tenant.tenant_id,
            run_id=None,
            trajectory=("receive",),
        )


def _client(
    *,
    environment: str = "test",
    packages_dir: Path | None = None,
    principal: Principal | None = PLATFORM,
    service: StubOnboardingService | None = None,
    configs: StubConfigService | None = None,
    harness: StubHarness | None = None,
) -> tuple[TestClient, StubOnboardingService, StubConfigService, StubHarness]:
    app = create_app(environment=environment)
    onboarding = service or StubOnboardingService()
    config_service = configs or StubConfigService()
    agent = harness or StubHarness()
    app.state.onboarding_service = onboarding
    app.state.config_service = config_service
    app.state.agent_harness = agent
    if packages_dir is not None:
        app.state.tenant_packages_dir = packages_dir
    if principal is not None:
        app.state.admin_authenticator = admin_authenticator({TOKEN: principal})
    return TestClient(app, headers=bearer(TOKEN)), onboarding, config_service, agent


def test_instituciones_routes_are_absent_in_production() -> None:
    app = create_app(environment="production")
    paths = set(app.openapi()["paths"])
    assert "/admin/instituciones" not in paths
    assert "/admin/instituciones/{slug}/chat" not in paths
    assert "/v1/admin/tenants" not in paths or "GET" not in app.openapi()["paths"].get(
        "/v1/admin/tenants", {}
    )
    client = TestClient(app)
    listed = client.get("/admin/instituciones")
    chat = client.get(f"/admin/instituciones/{SLUG}/chat")
    assert listed.status_code == 404
    assert chat.status_code == 404


def test_get_instituciones_lists_visible_slugs(tmp_path: Path) -> None:
    client, _, _, _ = _client(packages_dir=tmp_path)
    response = client.get("/admin/instituciones")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert SLUG in response.text
    assert "Clinica Norte" in response.text
    assert "api_key" not in response.text
    assert TOKEN not in response.text


def test_form_only_exposes_current_package_fields(tmp_path: Path) -> None:
    client, _, _, _ = _client(packages_dir=tmp_path)
    html = client.get("/admin/instituciones").text
    for field in (
        "slug",
        "display_name",
        "tone",
        "instructions",
        "enabled_skills",
        "enabled_tools",
        "mcp_server_id",
        "mcp_capabilities",
        "mcp_credentials_reference",
        "knowledge_text",
    ):
        assert field in html
    assert "cuit" not in html
    assert "api_key" not in html
    assert "whatsapp" not in html.lower() or "aspecto" in html.lower()
    assert "URLSearchParams" in html
    assert "application/x-www-form-urlencoded" in html


def test_post_alta_writes_package_provisions_and_lab_enables(tmp_path: Path) -> None:
    client, service, _, _ = _client(packages_dir=tmp_path)
    response = client.post(
        "/admin/instituciones",
        data={
            "slug": "sede-oeste",
            "display_name": "Sede Oeste",
            "tone": "cordial",
            "instructions": "Sea breve.",
            "enabled_skills": ["faq"],
            "mcp_server_id": "fake-oeste",
            "mcp_capabilities": [],
            "mcp_credentials_reference": "sm://sede-oeste/mcp/appointments",
        },
    )
    assert response.status_code == 200
    package_dir = tmp_path / "sede-oeste"
    assert package_dir.is_dir()
    assert (package_dir / "tenant.yaml").is_file()
    assert service.provisioned
    assert service.provisioned[0].tenant.slug == "sede-oeste"
    assert service.lab_enabled == ["sede-oeste"]
    assert TOKEN not in response.text


def test_post_json_alta_uses_same_contract(tmp_path: Path) -> None:
    client, service, _, _ = _client(packages_dir=tmp_path)
    response = client.post(
        "/v1/admin/instituciones",
        json={
            "slug": "sede-este",
            "display_name": "Sede Este",
            "tone": "formal",
            "mcp_server_id": "fake-este",
            "mcp_credentials_reference": "sm://sede-este/mcp/appointments",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["slug"] == "sede-este"
    assert service.lab_enabled == ["sede-este"]


def test_get_tenants_json_lists_items(tmp_path: Path) -> None:
    client, _, _, _ = _client(packages_dir=tmp_path)
    response = client.get("/v1/admin/tenants")
    assert response.status_code == 200
    items = response.json()
    assert items[0]["slug"] == SLUG
    assert items[0]["display_name"] == "Clinica Norte"


def test_chat_get_renders_whatsapp_shell(tmp_path: Path) -> None:
    client, _, _, _ = _client(packages_dir=tmp_path)
    response = client.get(f"/admin/instituciones/{SLUG}/chat")
    assert response.status_code == 200
    assert "Clinica Norte" in response.text or SLUG in response.text
    assert "chat" in response.text.lower() or "whatsapp" in response.text.lower()
    assert "URLSearchParams" in response.text
    assert TOKEN not in response.text


def test_chat_post_calls_harness_with_slug_tenant_context(tmp_path: Path) -> None:
    client, service, configs, harness = _client(packages_dir=tmp_path)
    # Poison the startup map: chat must not read it.
    client.app.state.channel_integration_ids = {
        ("simulated", f"{SLUG}-simulated"): uuid4()
    }
    response = client.post(
        f"/admin/instituciones/{SLUG}/chat",
        data={"text": "horario sucursal", "history": "[]"},
    )
    assert response.status_code == 200
    assert "horario sucursal" in response.text
    assert "lab-reply" in response.text
    assert configs.captures == [
        TenantIdentity(tenant_id=TENANT_ID, tenant_slug=SLUG)
    ]
    assert len(harness.messages) == 1
    tenant, message = harness.messages[0]
    assert tenant.tenant_id == TENANT_ID
    assert tenant.tenant_slug == SLUG
    assert message.channel == "simulated"
    assert message.channel_integration_id == CHANNEL_ID
    assert message.text == "horario sucursal"
    assert service.channel_lookups
    assert service.channel_lookups[0].tenant_slug == SLUG
    assert "X-Simulated-Signature" not in response.request.headers
    assert TOKEN not in response.text


def test_chat_does_not_require_simulated_channel_signature(tmp_path: Path) -> None:
    client, _, _, harness = _client(packages_dir=tmp_path)
    response = client.post(
        f"/admin/instituciones/{SLUG}/chat",
        data={"text": "hola"},
    )
    assert response.status_code == 200
    assert harness.messages
    assert "x-simulated-signature" not in {k.lower() for k in response.request.headers}
