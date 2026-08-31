"""HTML lab pages for institutions (AC-P13-004, AC-P13-005, AC-P13-006, AC-P15-005).

No PostgreSQL: collaborators are stubs. The suite checks routes, form fields,
provision/lab_enable wiring and that chat calls the harness with the slug's
TenantContext — not the simulated-channel signature. Discovery uses an
injected stub; this file does not open a network socket.
"""

from __future__ import annotations

import json
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
from ia_mcp.onboarding.lab_mcp import LAB_ENDPOINTS_FILE
from ia_mcp.onboarding.loader import load_yaml
from ia_mcp.onboarding.models import TenantPackage
from ia_mcp.onboarding.service import PLATFORM_ADMIN, TenantOnboardingService
from ia_mcp.tenancy.models import TenantContext, TenantIdentity
from tests.fixtures.admin_auth import admin_authenticator, bearer

LAN_SSE = "http://192.168.1.247:8001/sse"

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


class StubDiscoverer:
    def __init__(self, names: tuple[str, ...] = ("crear_turno",)) -> None:
        self.names = names
        self.endpoints: list[str] = []

    async def list_names(self, endpoint: str) -> tuple[str, ...]:
        self.endpoints.append(endpoint)
        return self.names


class FailingDiscoverer:
    async def list_names(self, endpoint: str) -> tuple[str, ...]:
        del endpoint
        raise TimeoutError("upstream body must not leak")


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
    discoverer: StubDiscoverer | None = None,
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
    if discoverer is not None:
        app.state.lab_mcp_discoverer = discoverer
    if principal is not None:
        app.state.admin_authenticator = admin_authenticator({TOKEN: principal})
    headers = bearer(TOKEN) if principal is not None else {}
    return TestClient(app, headers=headers), onboarding, config_service, agent


def _anonymous_client(
    packages_dir: Path,
    service: StubOnboardingService | None = None,
    configs: StubConfigService | None = None,
    harness: StubHarness | None = None,
) -> tuple[TestClient, StubOnboardingService, StubConfigService, StubHarness]:
    app = create_app(environment="test")
    onboarding = service or StubOnboardingService()
    config_service = configs or StubConfigService()
    agent = harness or StubHarness()
    app.state.onboarding_service = onboarding
    app.state.config_service = config_service
    app.state.agent_harness = agent
    app.state.tenant_packages_dir = packages_dir
    app.state.admin_authenticator = admin_authenticator({TOKEN: PLATFORM})
    return TestClient(app), onboarding, config_service, agent


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
        "mcp_endpoint",
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
    assert "simular whatsapp" in response.text.lower()
    assert "simulated" in response.text.lower()
    assert "URLSearchParams" in response.text
    assert TOKEN not in response.text


def test_post_alta_with_mcp_endpoint_discovers_tools_and_redirects_to_chat(
    tmp_path: Path,
) -> None:
    discoverer = StubDiscoverer(("crear_turno",))
    client, service, _, _ = _client(packages_dir=tmp_path, discoverer=discoverer)
    response = client.post(
        "/admin/instituciones",
        data={
            "slug": "sede-mcp",
            "display_name": "Sede MCP",
            "tone": "cordial",
            "enabled_skills": ["faq"],
            "mcp_server_id": "soloturnos",
            "mcp_capabilities": [],
            "mcp_credentials_reference": "sm://sede-mcp/mcp/appointments",
            "mcp_endpoint": LAN_SSE,
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    location = response.headers["location"]
    assert location.endswith("/admin/instituciones/sede-mcp/chat")
    assert TOKEN not in response.text
    assert TOKEN not in location
    assert discoverer.endpoints == [LAN_SSE]
    endpoints = json.loads((tmp_path / LAB_ENDPOINTS_FILE).read_text(encoding="utf-8"))
    assert endpoints == {"soloturnos": LAN_SSE}
    integrations = load_yaml(
        (tmp_path / "sede-mcp" / "integrations.yaml").read_text(encoding="utf-8")
    )
    config = load_yaml((tmp_path / "sede-mcp" / "config.yaml").read_text(encoding="utf-8"))
    assert "crear_turno" in integrations["integrations"][0]["capabilities"]
    assert "crear_turno" in config["enabled_tools"]
    assert "faq" in config["enabled_skills"]
    assert LAN_SSE not in (tmp_path / "sede-mcp" / "integrations.yaml").read_text(
        encoding="utf-8"
    )
    assert LAN_SSE not in (tmp_path / "sede-mcp" / "config.yaml").read_text(
        encoding="utf-8"
    )
    assert service.lab_enabled == ["sede-mcp"]
    chat = client.get(location)
    assert chat.status_code == 200
    assert "simular whatsapp" in chat.text.lower()
    assert TOKEN not in chat.text
    assert LAN_SSE not in chat.text


def test_discovery_failure_still_saves_and_shows_safe_notice(
    tmp_path: Path,
) -> None:
    client, service, _, _ = _client(packages_dir=tmp_path)
    client.app.state.lab_mcp_discoverer = FailingDiscoverer()
    response = client.post(
        "/admin/instituciones",
        data={
            "slug": "sede-fallo",
            "display_name": "Sede Fallo",
            "tone": "formal",
            "enabled_skills": ["faq"],
            "mcp_server_id": "soloturnos",
            "mcp_credentials_reference": "sm://sede-fallo/mcp/appointments",
            "mcp_endpoint": LAN_SSE,
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    location = response.headers["location"]
    assert location.endswith(
        "/admin/instituciones/sede-fallo/chat?notice=discovery_unavailable"
    )
    assert "upstream body must not leak" not in response.text
    assert TOKEN not in response.text
    assert (tmp_path / "sede-fallo" / "tenant.yaml").is_file()
    endpoints = json.loads((tmp_path / LAB_ENDPOINTS_FILE).read_text(encoding="utf-8"))
    assert endpoints["soloturnos"] == LAN_SSE
    assert service.lab_enabled == ["sede-fallo"]
    chat = client.get(location)
    assert chat.status_code == 200
    assert "The MCP catalog could not be listed." in chat.text
    assert "upstream body must not leak" not in chat.text
    assert TOKEN not in chat.text


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


def test_html_without_bearer_uses_roster_platform_admin(tmp_path: Path) -> None:
    """Browser lab pages read the process roster; the token stays out of HTML."""
    service = StubOnboardingService()
    configs = StubConfigService()
    harness = StubHarness()
    bare, _, _, _ = _anonymous_client(tmp_path, service, configs, harness)
    listed = bare.get("/admin/instituciones")
    assert listed.status_code == 200
    assert SLUG in listed.text
    assert TOKEN not in listed.text
    chat = bare.get(f"/admin/instituciones/{SLUG}/chat")
    assert chat.status_code == 200
    assert TOKEN not in chat.text
    created = bare.post(
        "/admin/instituciones",
        data={
            "slug": "sede-lab",
            "display_name": "Sede Lab",
            "tone": "claro",
            "enabled_skills": ["faq"],
            "mcp_server_id": "fake-lab",
            "mcp_capabilities": [],
            "mcp_credentials_reference": "sm://sede-lab/mcp/appointments",
        },
    )
    assert created.status_code == 200
    assert service.lab_enabled[-1] == "sede-lab"
    assert TOKEN not in created.text
    spoken = bare.post(
        f"/admin/instituciones/{SLUG}/chat",
        data={"text": "horario", "history": "[]"},
    )
    assert spoken.status_code == 200
    assert harness.messages
    assert TOKEN not in spoken.text


def test_html_json_and_bad_bearer_still_require_a_presented_token(
    tmp_path: Path,
) -> None:
    bare, _, _, _ = _anonymous_client(tmp_path)
    listed_json = bare.get("/v1/admin/tenants")
    created_json = bare.post(
        "/v1/admin/instituciones",
        json={
            "slug": "sede-json",
            "display_name": "Sede JSON",
            "tone": "formal",
            "mcp_server_id": "fake-json",
            "mcp_credentials_reference": "sm://sede-json/mcp/appointments",
        },
    )
    rejected = bare.get(
        "/admin/instituciones",
        headers={"Authorization": "Bearer not-the-roster-token"},
    )
    assert listed_json.status_code == 401
    assert created_json.status_code == 401
    assert rejected.status_code == 401
    assert TOKEN not in rejected.text


def test_html_without_roster_secret_stays_unauthorized(tmp_path: Path) -> None:
    client, _, _, _ = _client(packages_dir=tmp_path, principal=None)
    listed = client.get("/admin/instituciones")
    chat = client.get(f"/admin/instituciones/{SLUG}/chat")
    assert listed.status_code == 401
    assert chat.status_code == 401


def test_chat_does_not_require_simulated_channel_signature(tmp_path: Path) -> None:
    client, _, _, harness = _client(packages_dir=tmp_path)
    response = client.post(
        f"/admin/instituciones/{SLUG}/chat",
        data={"text": "hola"},
    )
    assert response.status_code == 200
    assert harness.messages
    assert "x-simulated-signature" not in {k.lower() for k in response.request.headers}
