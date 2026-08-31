"""Composition root wiring matrix.

No PostgreSQL is required: `create_async_engine` is lazy, so the graph can be
built against an unreachable URL as long as nothing issues a query. Coroutines
are wrapped with `asyncio.run` because pytest-asyncio is not installed.
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ia_mcp.agent_runtime.harness import AgentHarness
from ia_mcp.agent_runtime.ports import FakeLLM
from ia_mcp.api.app import create_app
from ia_mcp.api.auth.service_token import ADMIN_PRINCIPALS, ServiceTokenAuthenticator
from ia_mcp.api.composition import (
    EmptyKnowledgeSearch,
    RuntimeLabMcpDiscoverer,
    TenantToolExecutors,
    admin_authenticator_from,
    allowed_hosts_for,
    attach_runtime,
    build_runtime,
    mcp_endpoints_from,
)
from ia_mcp.configuration.models import AgentConfig, TenantConfig
from ia_mcp.configuration.service import ConfigurationService
from ia_mcp.contracts.common import ToolResult
from ia_mcp.contracts.errors import ToolErrorCode
from ia_mcp.knowledge.lab_search import LabKnowledgeSearch
from ia_mcp.llm.gemini import GeminiLLM, UrllibGeminiTransport
from ia_mcp.mcp.client import SseMcpClient
from ia_mcp.mcp.discovery import DiscoveredTool, DiscoveredToolCatalog
from ia_mcp.mcp.executor import McpTarget, ToolCall
from ia_mcp.mcp.fakes.appointments import FakeAppointmentCapability
from ia_mcp.onboarding.lab_mcp import write_lab_mcp_endpoint
from ia_mcp.onboarding.preflight import SecretResolvabilityCheck
from ia_mcp.onboarding.service import TenantOnboardingService
from ia_mcp.shared.errors import DomainError
from ia_mcp.skills.registry import SkillRegistry
from ia_mcp.tenancy.models import TenantContext
from ia_mcp.tenancy.service import TenantService
from scripts.check_tenant_specific_core import find_slug_branches
from tests.integration.api.test_simulated_messages import (
    FROZEN_NOW,
    FakeChannelRepository,
    signed_simulated_headers,
    valid_body,
)

# Port 1 is never a PostgreSQL listener; the graph must not connect while building.
UNREACHABLE_DATABASE_URL = "postgresql+psycopg://ia_mcp@127.0.0.1:1/ia_mcp_composition"
GEMINI_SECRET_VARIABLE = "IA_MCP_SECRET_PLATFORM_LLM_GEMINI"
GEMINI_TEST_KEY = "test-not-a-secret"
COMPOSITION_PATH = Path("src/ia_mcp/api/composition.py")
READ_SERVER_TOOLS = frozenset({"appointments.search", "appointments.get"})
MCP_HOST = "mcp.example"
MCP_ENDPOINT = f"https://{MCP_HOST}/sse"
SERVER_ID = "mcp-appointments"
TENANT_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
RUN_ID = uuid4()
GENERIC_TOOL = "crear_turno"
TOKEN_REFERENCE = "sm://admin/composition"
TOKEN_VARIABLE = "IA_MCP_SECRET_ADMIN_COMPOSITION"
ADMIN_TOKEN = "svctest-composition-token"
SEARCH_ARGS: dict[str, Any] = {
    "specialty": "cardiologia",
    "date_from": "2026-09-01",
    "date_to": "2026-09-01",
}

RUNTIME_STATE = (
    "tenant_service",
    "config_service",
    "agent_harness",
    "channel_integration_ids",
    "tool_executor",
    "onboarding_service",
    "tenant_packages_dir",
)


def _run[T](coro: Coroutine[object, object, T]) -> T:
    return asyncio.run(coro)


def _tenant() -> TenantContext:
    return TenantContext(
        tenant_id=TENANT_ID,
        tenant_slug="tenant-a",
        config_version=1,
        correlation_id=uuid4(),
    )


def _config(*enabled_tools: str) -> TenantConfig:
    return TenantConfig(
        tenant_id=TENANT_ID,
        version=1,
        agent=AgentConfig(tone="cordial"),
        enabled_skills=frozenset({"appointments"}),
        enabled_tools=frozenset(enabled_tools),
    )


class StubIntegrations:
    """MCP server the tenant declared, with the tools it declared for it."""

    def __init__(self, tools: frozenset[str], *, endpoint: str = "") -> None:
        self._tools = tools
        self._endpoint = endpoint
        self.tenants: list[TenantContext] = []

    async def declared_tools(self, tenant: TenantContext) -> frozenset[str]:
        self.tenants.append(tenant)
        return self._tools

    async def resolve(self, tenant: TenantContext, capability: str) -> McpTarget:
        del tenant, capability
        return McpTarget(
            server_id=SERVER_ID,
            allowed_tools=self._tools,
            endpoint=self._endpoint,
            auth_reference="",
        )


class TransportSpy:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def call_tool(
        self,
        tenant: TenantContext,
        target: McpTarget,
        name: str,
        arguments: dict[str, Any],
    ) -> ToolResult[Any]:
        del tenant, target, arguments
        self.calls.append(name)
        return ToolResult[Any](ok=True, value={"status": "ok"})


def _executors(
    *,
    declared: frozenset[str],
    transport: TransportSpy | None = None,
    allowed_hosts: tuple[str, ...] = (),
) -> TenantToolExecutors:
    return TenantToolExecutors(
        integrations=StubIntegrations(
            declared, endpoint=MCP_ENDPOINT if transport is not None else ""
        ),
        capability=FakeAppointmentCapability(),
        skills=SkillRegistry(),
        allowed_hosts=allowed_hosts,
        transport=transport,
    )


def test_test_environment_does_not_autowire(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", UNREACHABLE_DATABASE_URL)
    app = create_app(environment="test")
    for name in RUNTIME_STATE:
        assert getattr(app.state, name, None) is None


def test_development_without_database_url_does_not_autowire(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    app = create_app(environment="development")
    for name in RUNTIME_STATE:
        assert getattr(app.state, name, None) is None


def test_development_with_database_url_attaches_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", UNREACHABLE_DATABASE_URL)
    app = create_app(environment="development")
    assert isinstance(app.state.tenant_service, TenantService)
    assert isinstance(app.state.config_service, ConfigurationService)
    assert isinstance(app.state.agent_harness, AgentHarness)
    assert isinstance(app.state.channel_integration_ids, dict)
    assert isinstance(app.state.tool_executor, TenantToolExecutors)
    assert isinstance(app.state.onboarding_service, TenantOnboardingService)
    assert isinstance(app.state.lab_mcp_discoverer, RuntimeLabMcpDiscoverer)


def test_tenant_packages_dir_is_published_from_the_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("DATABASE_URL", UNREACHABLE_DATABASE_URL)
    monkeypatch.setenv("IA_MCP_TENANT_PACKAGES_DIR", str(tmp_path))
    app = create_app(environment="development")
    assert app.state.tenant_packages_dir == tmp_path


def test_runtime_without_packages_dir_publishes_no_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unset means the HTTP boundary has no root, never an arbitrary path."""
    monkeypatch.delenv("IA_MCP_TENANT_PACKAGES_DIR", raising=False)
    runtime = build_runtime(
        environment="development",
        environ={"DATABASE_URL": UNREACHABLE_DATABASE_URL},
    )
    assert runtime is not None
    assert runtime.tenant_packages_dir is None
    assert isinstance(runtime.onboarding_service, TenantOnboardingService)


def test_blank_packages_dir_is_not_a_root() -> None:
    runtime = build_runtime(
        environment="development",
        environ={
            "DATABASE_URL": UNREACHABLE_DATABASE_URL,
            "IA_MCP_TENANT_PACKAGES_DIR": "   ",
        },
    )
    assert runtime is not None
    assert runtime.tenant_packages_dir is None


def test_production_mounts_no_simulated_route_and_no_fakes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", UNREACHABLE_DATABASE_URL)
    app = create_app(environment="production")
    # Included routers are not flattened into `app.routes` on this FastAPI
    # version, so reading them there would pass even if the route were mounted.
    paths = set(app.openapi()["paths"])
    assert "/v1/simulated/messages" not in paths
    assert TestClient(app).post("/v1/simulated/messages", json={}).status_code == 404
    for name in RUNTIME_STATE:
        assert getattr(app.state, name, None) is None


def test_injected_tenant_service_still_acknowledges_in_test_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", UNREACHABLE_DATABASE_URL)
    app = create_app(environment="test")
    app.state.tenant_service = TenantService(
        FakeChannelRepository({("simulated", "acct-a"): TENANT_ID})
    )
    app.state.simulated_clock = lambda: FROZEN_NOW
    body = valid_body()
    response = TestClient(app).post(
        "/v1/simulated/messages",
        json=body,
        headers=signed_simulated_headers(account="acct-a", body=body),
    )
    assert response.status_code == 202
    assert "run_id" not in response.json()


def test_runtime_builds_generic_transport_from_configured_endpoints() -> None:
    runtime = build_runtime(
        environment="development",
        environ={
            "DATABASE_URL": UNREACHABLE_DATABASE_URL,
            "IA_MCP_MCP_ENDPOINTS": f"{SERVER_ID}={MCP_ENDPOINT}",
        },
    )
    assert runtime is not None
    assert isinstance(runtime.tool_executor.transport, SseMcpClient)
    assert runtime.tool_executor.allowed_hosts == (MCP_HOST,)


def test_runtime_without_configured_endpoints_has_no_generic_transport() -> None:
    runtime = build_runtime(
        environment="development",
        environ={"DATABASE_URL": UNREACHABLE_DATABASE_URL},
    )
    assert runtime is not None
    assert runtime.tool_executor.transport is None
    assert runtime.tool_executor.allowed_hosts == ()


def test_generic_transport_requires_allowed_hosts() -> None:
    with pytest.raises(ValueError) as caught:
        _executors(declared=frozenset({GENERIC_TOOL}), transport=TransportSpy())
    assert "allowed_hosts" in str(caught.value)


def test_executor_intersects_tenant_config_with_declared_catalog() -> None:
    executors = _executors(declared=frozenset({"appointments.search", GENERIC_TOOL}))
    tenant = _tenant()

    async def _scenario() -> tuple[ToolResult[Any], ToolResult[Any]]:
        executor = await executors.for_tenant(
            tenant, _config("appointments.search"), "appointments"
        )
        allowed = await executor.execute(
            tenant, RUN_ID, ToolCall(name="appointments.search", arguments=SEARCH_ARGS)
        )
        denied = await executor.execute(
            tenant, RUN_ID, ToolCall(name=GENERIC_TOOL, arguments={})
        )
        return allowed, denied

    allowed, denied = _run(_scenario())
    assert allowed.ok is True
    assert denied.ok is False
    assert denied.error is not None
    assert denied.error.code == ToolErrorCode.FORBIDDEN


def test_authorized_generic_tool_reaches_the_mcp_client() -> None:
    transport = TransportSpy()
    executors = _executors(
        declared=frozenset({GENERIC_TOOL}),
        transport=transport,
        allowed_hosts=(MCP_HOST,),
    )
    tenant = _tenant()

    async def _scenario() -> ToolResult[Any]:
        executor = await executors.for_tenant(
            tenant, _config(GENERIC_TOOL), "appointments"
        )
        return await executor.execute(
            tenant, RUN_ID, ToolCall(name=GENERIC_TOOL, arguments={})
        )

    result = _run(_scenario())
    assert result.ok is True
    assert transport.calls == [GENERIC_TOOL]


def test_generic_tool_is_forbidden_without_transport() -> None:
    executors = _executors(declared=frozenset({GENERIC_TOOL}))
    tenant = _tenant()

    async def _scenario() -> ToolResult[Any]:
        executor = await executors.for_tenant(
            tenant, _config(GENERIC_TOOL), "appointments"
        )
        return await executor.execute(
            tenant, RUN_ID, ToolCall(name=GENERIC_TOOL, arguments={})
        )

    result = _run(_scenario())
    assert result.ok is False
    assert result.error is not None
    assert result.error.code == ToolErrorCode.FORBIDDEN


def test_no_declared_roster_publishes_no_authenticator() -> None:
    """An unconfigured process must refuse callers, never trust one."""
    assert admin_authenticator_from({}) is None
    assert admin_authenticator_from({ADMIN_PRINCIPALS: "  "}) is None


def test_declared_roster_authenticates_its_token_from_the_environment() -> None:
    authenticator = admin_authenticator_from(
        {
            ADMIN_PRINCIPALS: (
                f"principal={TENANT_ID};roles=operator;secret={TOKEN_REFERENCE};"
                f"tenant_id={TENANT_ID};tenant_slug=tenant-a"
            ),
            TOKEN_VARIABLE: ADMIN_TOKEN,
        }
    )
    assert authenticator is not None
    principal = _run(authenticator.authenticate(f"Bearer {ADMIN_TOKEN}"))
    assert principal is not None
    assert principal.roles == frozenset({"operator"})
    assert principal.tenant_slug == "tenant-a"
    assert _run(authenticator.authenticate(f"Bearer {ADMIN_TOKEN}x")) is None


def test_a_declared_principal_without_its_secret_authenticates_nobody() -> None:
    authenticator = admin_authenticator_from(
        {ADMIN_PRINCIPALS: f"principal={TENANT_ID};roles=platform_admin;secret={TOKEN_REFERENCE}"}
    )
    assert authenticator is not None
    assert _run(authenticator.authenticate(f"Bearer {ADMIN_TOKEN}")) is None


def test_create_app_publishes_the_authenticator_in_every_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(ADMIN_PRINCIPALS, raising=False)
    assert create_app(environment="production").state.admin_authenticator is None
    monkeypatch.setenv(
        ADMIN_PRINCIPALS,
        f"principal={TENANT_ID};roles=platform_admin;secret={TOKEN_REFERENCE}",
    )
    monkeypatch.setenv(TOKEN_VARIABLE, ADMIN_TOKEN)
    for environment in ("production", "development", "test"):
        published = create_app(environment=environment).state.admin_authenticator
        assert isinstance(published, ServiceTokenAuthenticator), environment


def test_runtime_wires_the_environment_resolver_into_the_secret_check() -> None:
    """The preflight secret check must report what this process can reach."""
    runtime = build_runtime(
        environment="development",
        environ={
            "DATABASE_URL": UNREACHABLE_DATABASE_URL,
            TOKEN_VARIABLE: ADMIN_TOKEN,
        },
    )
    assert runtime is not None
    checks = {
        check.name: check for check in runtime.onboarding_service.preflight_checks
    }
    secrets = checks["secrets_resolvable"]
    assert isinstance(secrets, SecretResolvabilityCheck)
    tenant = _tenant()
    assert _run(secrets.secrets.resolvable(tenant, TOKEN_REFERENCE)) is True
    assert _run(secrets.secrets.resolvable(tenant, "sm://tenant-a/mcp/absent")) is False


def test_endpoints_are_read_from_the_environment_not_hardcoded() -> None:
    endpoints = mcp_endpoints_from(
        {"IA_MCP_MCP_ENDPOINTS": f"{SERVER_ID}={MCP_ENDPOINT}, lan=http://lan.example"}
    )
    assert endpoints == {SERVER_ID: MCP_ENDPOINT, "lan": "http://lan.example"}
    assert allowed_hosts_for(endpoints) == (MCP_HOST, "http://lan.example")
    assert mcp_endpoints_from({}) == {}


def test_runtime_wires_gemini_when_platform_secret_is_set() -> None:
    runtime = build_runtime(
        environment="development",
        environ={
            "DATABASE_URL": UNREACHABLE_DATABASE_URL,
            GEMINI_SECRET_VARIABLE: GEMINI_TEST_KEY,
        },
    )
    assert runtime is not None
    assert isinstance(runtime.agent_harness._llm, GeminiLLM)
    assert isinstance(runtime.agent_harness._llm._transport, UrllibGeminiTransport)


def test_runtime_keeps_fake_llm_when_gemini_secret_is_absent() -> None:
    runtime = build_runtime(
        environment="development",
        environ={"DATABASE_URL": UNREACHABLE_DATABASE_URL},
    )
    assert runtime is not None
    assert isinstance(runtime.agent_harness._llm, FakeLLM)


def test_runtime_keeps_fake_llm_when_gemini_secret_is_blank() -> None:
    runtime = build_runtime(
        environment="development",
        environ={
            "DATABASE_URL": UNREACHABLE_DATABASE_URL,
            GEMINI_SECRET_VARIABLE: "   ",
        },
    )
    assert runtime is not None
    assert isinstance(runtime.agent_harness._llm, FakeLLM)


def test_runtime_wires_lab_knowledge_when_packages_dir_is_set(tmp_path: Path) -> None:
    runtime = build_runtime(
        environment="development",
        environ={
            "DATABASE_URL": UNREACHABLE_DATABASE_URL,
            "IA_MCP_TENANT_PACKAGES_DIR": str(tmp_path),
        },
    )
    assert runtime is not None
    assert isinstance(runtime.agent_harness._knowledge, LabKnowledgeSearch)


def test_runtime_keeps_empty_knowledge_when_packages_dir_is_absent() -> None:
    runtime = build_runtime(
        environment="development",
        environ={"DATABASE_URL": UNREACHABLE_DATABASE_URL},
    )
    assert runtime is not None
    assert isinstance(runtime.agent_harness._knowledge, EmptyKnowledgeSearch)


def test_runtime_compiler_uses_process_read_server_tools() -> None:
    runtime = build_runtime(
        environment="development",
        environ={"DATABASE_URL": UNREACHABLE_DATABASE_URL},
    )
    assert runtime is not None
    compiler = runtime.agent_harness._compiler
    assert compiler._server_tools == READ_SERVER_TOOLS
    assert compiler._tenant_tools == {}
    assert compiler._mirror_tenant_tools is True


def test_runtime_merges_lab_endpoints_and_env_wins(tmp_path: Path) -> None:
    write_lab_mcp_endpoint(tmp_path, "soloturnos", "http://192.168.1.247:8001/sse")
    write_lab_mcp_endpoint(tmp_path, SERVER_ID, "https://from-json.example/sse")
    runtime = build_runtime(
        environment="development",
        environ={
            "DATABASE_URL": UNREACHABLE_DATABASE_URL,
            "IA_MCP_TENANT_PACKAGES_DIR": str(tmp_path),
            "IA_MCP_MCP_ENDPOINTS": f"{SERVER_ID}={MCP_ENDPOINT}",
        },
    )
    assert runtime is not None
    assert isinstance(runtime.tool_executor.transport, SseMcpClient)
    assert runtime.tool_executor.allowed_hosts == (
        "http://192.168.1.247",
        MCP_HOST,
    )


def test_runtime_lab_endpoints_alone_wire_transport(tmp_path: Path) -> None:
    write_lab_mcp_endpoint(tmp_path, "soloturnos", "http://192.168.1.247:8001/sse")
    runtime = build_runtime(
        environment="development",
        environ={
            "DATABASE_URL": UNREACHABLE_DATABASE_URL,
            "IA_MCP_TENANT_PACKAGES_DIR": str(tmp_path),
        },
    )
    assert runtime is not None
    assert isinstance(runtime.tool_executor.transport, SseMcpClient)
    assert runtime.tool_executor.allowed_hosts == ("http://192.168.1.247",)


def test_runtime_discoverer_lists_without_intersect_or_auth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[object, object, bool]] = []

    class FakeClient:
        def __init__(self, *, allowlist: object, timeout_seconds: float = 10.0) -> None:
            self.allowlist = allowlist
            del timeout_seconds

        async def list_tools(
            self,
            tenant: TenantContext,
            target: McpTarget,
            *,
            intersect_allowed: bool = True,
        ) -> DiscoveredToolCatalog:
            calls.append((tenant, target, intersect_allowed))
            return DiscoveredToolCatalog(
                server_id="lab",
                tools=(DiscoveredTool(name="crear_turno"),),
            )

    monkeypatch.setattr("ia_mcp.api.composition.SseMcpClient", FakeClient)
    names = _run(RuntimeLabMcpDiscoverer().list_names("https://mcp.example/sse"))
    assert names == ("crear_turno",)
    assert calls
    tenant, target, intersect = calls[0]
    assert isinstance(tenant, TenantContext)
    assert target.auth_reference == ""
    assert target.endpoint == "https://mcp.example/sse"
    assert intersect is False


def test_runtime_discoverer_rejects_userinfo() -> None:
    with pytest.raises(ValueError):
        _run(
            RuntimeLabMcpDiscoverer().list_names(
                "http://user:secret@192.168.1.247:8001/sse"
            )
        )


def test_runtime_discoverer_propagates_domain_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeClient:
        def __init__(self, *, allowlist: object, timeout_seconds: float = 10.0) -> None:
            del allowlist, timeout_seconds

        async def list_tools(
            self,
            tenant: TenantContext,
            target: McpTarget,
            *,
            intersect_allowed: bool = True,
        ) -> DiscoveredToolCatalog:
            del tenant, target, intersect_allowed
            raise DomainError(
                code="upstream_unavailable",
                safe_message="The MCP server is unavailable.",
                retryable=True,
            )

    monkeypatch.setattr("ia_mcp.api.composition.SseMcpClient", FakeClient)
    with pytest.raises(DomainError) as caught:
        _run(RuntimeLabMcpDiscoverer().list_names("https://mcp.example/sse"))
    assert caught.value.code == "upstream_unavailable"
    assert "secret" not in caught.value.safe_message.lower()


def test_attach_runtime_publishes_lab_mcp_discoverer() -> None:
    runtime = build_runtime(
        environment="development",
        environ={"DATABASE_URL": UNREACHABLE_DATABASE_URL},
    )
    assert runtime is not None
    app = FastAPI()
    attach_runtime(app, runtime)
    assert isinstance(app.state.lab_mcp_discoverer, RuntimeLabMcpDiscoverer)


def test_runtime_wiring_does_not_branch_on_tenant_identity() -> None:
    """The same process collaborators serve every tenant; no slug fork in Core."""
    source = COMPOSITION_PATH.read_text(encoding="utf-8")
    assert find_slug_branches(source) == ()
    assert "if tenant_id" not in source
    assert "match tenant_id" not in source
    runtime_a = build_runtime(
        environment="development",
        environ={
            "DATABASE_URL": UNREACHABLE_DATABASE_URL,
            GEMINI_SECRET_VARIABLE: GEMINI_TEST_KEY,
            "IA_MCP_TENANT_PACKAGES_DIR": "/tmp/packages-a",
        },
    )
    runtime_b = build_runtime(
        environment="development",
        environ={
            "DATABASE_URL": UNREACHABLE_DATABASE_URL,
            GEMINI_SECRET_VARIABLE: GEMINI_TEST_KEY,
            "IA_MCP_TENANT_PACKAGES_DIR": "/tmp/packages-b",
        },
    )
    assert runtime_a is not None
    assert runtime_b is not None
    assert isinstance(runtime_a.agent_harness._llm, GeminiLLM)
    assert isinstance(runtime_b.agent_harness._llm, GeminiLLM)
    assert isinstance(runtime_a.agent_harness._knowledge, LabKnowledgeSearch)
    assert isinstance(runtime_b.agent_harness._knowledge, LabKnowledgeSearch)
    assert runtime_a.agent_harness._compiler._server_tools == READ_SERVER_TOOLS
    assert runtime_b.agent_harness._compiler._server_tools == READ_SERVER_TOOLS
