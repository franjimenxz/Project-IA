"""Runtime composition root.

Builds the collaborator graph the HTTP process needs to run a turn and hands it
to `create_app`. It only constructs and connects existing collaborators: no
domain rule, no tenant branch and no credential value lives here.

Development reads three variables:

- `DATABASE_URL`, already used by `ia_mcp.onboarding.cli`.
- `IA_MCP_MCP_ENDPOINTS`, an optional `server_id=endpoint` list (comma
  separated) that maps the MCP servers tenants declared to the addresses this
  deployment may reach. Development also merges
  `{IA_MCP_TENANT_PACKAGES_DIR}/lab_mcp_endpoints.json`; env wins on the same
  `server_id`. The host allowlist is derived from that merged map, so no host
  is hardcoded in Core. Without any endpoint there is no generic MCP
  transport.
- `IA_MCP_TENANT_PACKAGES_DIR`, an optional absolute directory the onboarding
  HTTP boundary may read tenant packages from. It is the only root that
  boundary accepts, so without it every request naming a `package_path` is
  refused. The CLI is unaffected: an operator keeps passing local paths.

Two more are read in every environment, not only in development, because they
decide who may reach the administrative plane and how a credential is found:

- `IA_MCP_ADMIN_PRINCIPALS`, the roster of administrative principals and the
  `sm://` reference naming each one's service token (see
  `ia_mcp.api.auth.service_token`). Without it no principal is declared and
  every administrative endpoint answers 401.
- `IA_MCP_SECRET_*`, the values those references resolve to, read by
  `EnvironmentSecretResolver`. The same resolver backs the preflight secret
  check, so a tenant whose declared references are not exported cannot be
  activated.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Iterable, Mapping
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ia_mcp.agent_runtime.context_compiler import ContextCompiler
from ia_mcp.agent_runtime.harness import AgentHarness
from ia_mcp.agent_runtime.models import LLMDecision
from ia_mcp.agent_runtime.ports import FakeLLM, KnowledgeSearch, LLMPort
from ia_mcp.agent_runtime.run_repository import SqlAlchemyAgentRunRepository
from ia_mcp.api.auth.service_token import (
    ServiceTokenAuthenticator,
    admin_bindings_from,
)
from ia_mcp.configuration.adapters.environment_secrets import (
    EnvironmentSecretResolver,
    environment_variable_for,
)
from ia_mcp.configuration.adapters.sqlalchemy import SqlAlchemyConfigRepository
from ia_mcp.configuration.models import TenantConfig
from ia_mcp.configuration.service import ConfigurationService
from ia_mcp.conversation.adapters.sqlalchemy import SqlAlchemyConversationRepository
from ia_mcp.knowledge.lab_search import LabKnowledgeSearch
from ia_mcp.knowledge.models import KnowledgeHit, KnowledgeQuery
from ia_mcp.llm.gemini import GeminiLLM, UrllibGeminiTransport
from ia_mcp.mcp.capabilities.appointments import AppointmentCapability
from ia_mcp.mcp.client import SseMcpClient
from ia_mcp.mcp.executor import (
    HostAllowlist,
    McpTarget,
    McpTransportClient,
    ToolExecutor,
)
from ia_mcp.mcp.fakes.appointments import FakeAppointmentCapability
from ia_mcp.onboarding.lab_mcp import allowlist_entry_for, load_lab_mcp_endpoints
from ia_mcp.onboarding.preflight import (
    ResolvableSecretReferences,
    default_preflight_checks,
)
from ia_mcp.onboarding.service import TenantOnboardingService
from ia_mcp.skills.registry import SkillRegistry
from ia_mcp.tenancy.adapters.sqlalchemy import (
    SqlAlchemyChannelIntegrationRepository,
    SqlAlchemyMcpIntegrations,
)
from ia_mcp.tenancy.models import TenantContext
from ia_mcp.tenancy.service import TenantService

DEVELOPMENT = "development"
DATABASE_URL = "DATABASE_URL"
MCP_ENDPOINTS = "IA_MCP_MCP_ENDPOINTS"
TENANT_PACKAGES_DIR = "IA_MCP_TENANT_PACKAGES_DIR"
GEMINI_SECRET_REFERENCE = "sm://platform/llm/gemini"
READ_SERVER_TOOLS = frozenset({"appointments.search", "appointments.get"})
_LAB_DISCOVERY_TENANT = TenantContext(
    tenant_id=UUID(int=0),
    tenant_slug="lab-mcp-discovery",
    config_version=1,
    correlation_id=UUID(int=0),
)


class TenantMcpIntegrations(Protocol):
    """Tenant-scoped view of the MCP servers an institution declared."""

    async def declared_tools(self, tenant: TenantContext) -> frozenset[str]: ...

    async def resolve(self, tenant: TenantContext, capability: str) -> McpTarget: ...


class EmptyKnowledgeSearch:
    """Fail-closed knowledge port.

    `src/` ships no parser or embedding adapter and test fakes must not become
    runtime collaborators, so retrieval returns nothing and the FAQ skill
    answers `insufficient` instead of citing an unverified source.
    """

    async def search(
        self, tenant: TenantContext, query: KnowledgeQuery
    ) -> tuple[KnowledgeHit, ...]:
        del tenant, query
        return ()


def live_mcp_endpoints(
    packages_dir: Path | None, environ: Mapping[str, str]
) -> dict[str, str]:
    """Merge lab JSON with `IA_MCP_MCP_ENDPOINTS`. Env wins on the same key."""
    lab = load_lab_mcp_endpoints(packages_dir) if packages_dir is not None else {}
    return {**lab, **mcp_endpoints_from(environ)}


class LiveMcpEndpointResolver:
    """Overlays the current lab/env endpoint map onto a resolved target.

    `SqlAlchemyMcpIntegrations` snapshots endpoints at construction. The HTML
    form writes `lab_mcp_endpoints.json` in this same process, so each resolve
    reloads the merge and applies it. Auth is never invented.
    """

    def __init__(
        self,
        inner: TenantMcpIntegrations,
        *,
        packages_dir: Path | None,
        environ: Mapping[str, str],
    ) -> None:
        self._inner = inner
        self._packages_dir = packages_dir
        self._environ = environ

    async def declared_tools(self, tenant: TenantContext) -> frozenset[str]:
        return await self._inner.declared_tools(tenant)

    async def resolve(self, tenant: TenantContext, capability: str) -> McpTarget:
        target = await self._inner.resolve(tenant, capability)
        endpoint = live_mcp_endpoints(self._packages_dir, self._environ).get(
            target.server_id
        )
        if endpoint is None or endpoint == target.endpoint:
            return target
        return McpTarget(
            server_id=target.server_id,
            allowed_tools=target.allowed_tools,
            endpoint=endpoint,
            auth_reference=target.auth_reference,
        )


class TenantToolExecutors:
    """Builds a `ToolExecutor` for one tenant.

    The three allowlists an executor intersects are tenant data (the server
    catalog the tenant declared, its enabled tools and the active skill), so the
    composition root exposes this factory instead of one shared executor that
    could not be tenant-scoped. Development reloads the lab/env endpoint map on
    each `for_tenant` so a form save in this process is visible on the next turn.
    """

    def __init__(
        self,
        *,
        integrations: TenantMcpIntegrations,
        capability: AppointmentCapability,
        skills: SkillRegistry,
        allowed_hosts: Iterable[str] = (),
        transport: McpTransportClient | None = None,
        packages_dir: Path | None = None,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        hosts = tuple(allowed_hosts)
        if transport is not None and not hosts:
            raise ValueError(
                "transport requires allowed_hosts: generic invoke must fail "
                "closed before any network call"
            )
        if hosts and transport is None:
            raise ValueError(
                "allowed_hosts requires a transport: an allowlist without a "
                "client advertises a restriction that never applies"
            )
        self._integrations = integrations
        self._capability = capability
        self._skills = skills
        self._packages_dir = packages_dir
        self._environ = environ
        self.allowed_hosts = hosts
        self.transport = transport

    def _reload_live_endpoints(self) -> dict[str, str] | None:
        if self._packages_dir is None and self._environ is None:
            return None
        endpoints = live_mcp_endpoints(self._packages_dir, self._environ or {})
        hosts = allowed_hosts_for(endpoints)
        self.allowed_hosts = hosts
        self.transport = (
            SseMcpClient(allowlist=HostAllowlist(hosts)) if hosts else None
        )
        return endpoints

    async def for_tenant(
        self, tenant: TenantContext, config: TenantConfig, skill: str
    ) -> ToolExecutor:
        live = self._reload_live_endpoints()
        resolver: TenantMcpIntegrations = self._integrations
        if live is not None:
            resolver = LiveMcpEndpointResolver(
                self._integrations,
                packages_dir=self._packages_dir,
                environ=self._environ or {},
            )
        return ToolExecutor(
            server=await resolver.declared_tools(tenant),
            tenant=config.enabled_tools,
            skill=self._skills.resolve(skill, config).allowed_tools(config),
            capability=self._capability,
            resolver=resolver,
            allowed_hosts=self.allowed_hosts or None,
            transport=self.transport,
        )


@dataclass(frozen=True, slots=True)
class RuntimeGraph:
    engine: AsyncEngine
    channels: SqlAlchemyChannelIntegrationRepository
    tenant_service: TenantService
    config_service: ConfigurationService
    agent_harness: AgentHarness
    channel_integration_ids: dict[tuple[str, str], UUID]
    tool_executor: TenantToolExecutors
    onboarding_service: TenantOnboardingService
    tenant_packages_dir: Path | None


def mcp_endpoints_from(environ: Mapping[str, str]) -> dict[str, str]:
    endpoints: dict[str, str] = {}
    for entry in environ.get(MCP_ENDPOINTS, "").split(","):
        item = entry.strip()
        if not item:
            continue
        server_id, separator, endpoint = item.partition("=")
        if not separator or not server_id.strip() or not endpoint.strip():
            # The value may carry credentials, so the failure never echoes it.
            raise ValueError(f"{MCP_ENDPOINTS} entries must be server_id=endpoint")
        endpoints[server_id.strip()] = endpoint.strip()
    return endpoints


def admin_authenticator_from(
    environ: Mapping[str, str],
) -> ServiceTokenAuthenticator | None:
    """Authenticator for the administrative plane, or nothing when unconfigured.

    Built in every environment, unlike the runtime graph: authentication is not
    a development convenience. An empty roster publishes no authenticator at
    all, so the boundary refuses every caller instead of trusting one.
    """
    bindings = admin_bindings_from(environ)
    if not bindings:
        return None
    return ServiceTokenAuthenticator(bindings, EnvironmentSecretResolver(environ))


def tenant_packages_dir_from(environ: Mapping[str, str]) -> Path | None:
    """Root the onboarding HTTP boundary may read tenant packages from.

    Nothing is substituted when the variable is unset or blank: the boundary
    refuses every `package_path` instead of widening back into an arbitrary
    filesystem read. Containment is decided at the boundary, on the resolved
    path, so this returns the configured value unchanged.
    """
    value = environ.get(TENANT_PACKAGES_DIR, "").strip()
    return Path(value) if value else None


def allowed_hosts_for(endpoints: Mapping[str, str]) -> tuple[str, ...]:
    """Host allowlist entries for the endpoints this deployment configured.

    `https` hosts are listed bare; `http` keeps its scheme so plaintext stays
    opt-in per host, as ADR-005 requires.
    """
    hosts: list[str] = []
    for endpoint in endpoints.values():
        parsed = urlsplit(endpoint)
        host = (parsed.hostname or "").lower()
        if not host:
            continue
        entry = host if parsed.scheme == "https" else f"{parsed.scheme}://{host}"
        if entry not in hosts:
            hosts.append(entry)
    return tuple(hosts)


def build_runtime(
    *, environment: str, environ: Mapping[str, str]
) -> RuntimeGraph | None:
    """Build the development graph, or nothing when it must not be wired.

    `test` keeps injecting its own collaborators, `production` never receives
    fakes, and development without `DATABASE_URL` stays fail-closed.
    """
    if environment != DEVELOPMENT:
        return None
    database_url = environ.get(DATABASE_URL, "").strip()
    if not database_url:
        return None
    engine = create_async_engine(database_url)
    configs = SqlAlchemyConfigRepository(engine)
    skills = SkillRegistry()
    channels = SqlAlchemyChannelIntegrationRepository(engine)
    packages_dir = tenant_packages_dir_from(environ)
    endpoints = live_mcp_endpoints(packages_dir, environ)
    hosts = allowed_hosts_for(endpoints)
    transport = SseMcpClient(allowlist=HostAllowlist(hosts)) if hosts else None
    tool_executors = TenantToolExecutors(
        integrations=SqlAlchemyMcpIntegrations(engine, endpoints=endpoints),
        capability=FakeAppointmentCapability(),
        skills=skills,
        allowed_hosts=hosts,
        transport=transport,
        packages_dir=packages_dir,
        environ=environ,
    )
    gemini_api_key = environ.get(
        environment_variable_for(GEMINI_SECRET_REFERENCE), ""
    ).strip()
    llm: LLMPort
    if gemini_api_key:
        llm = GeminiLLM(transport=UrllibGeminiTransport(), api_key=gemini_api_key)
    else:
        llm = FakeLLM(LLMDecision(kind="insufficient", text="", source_ids=()))
    knowledge: KnowledgeSearch
    if packages_dir is not None:
        knowledge = LabKnowledgeSearch(packages_dir=packages_dir)
    else:
        knowledge = EmptyKnowledgeSearch()
    harness = AgentHarness(
        conversations=SqlAlchemyConversationRepository(engine),
        runs=SqlAlchemyAgentRunRepository(engine),
        configs=configs,
        skills=skills,
        compiler=ContextCompiler(
            configs=configs,
            skills=skills,
            tenant_tools={},
            server_tools=READ_SERVER_TOOLS,
            mirror_tenant_tools=True,
        ),
        knowledge=knowledge,
        llm=llm,
        executors=tool_executors,
        max_tool_iterations=4,
        turn_deadline_seconds=30.0,
    )
    return RuntimeGraph(
        engine=engine,
        channels=channels,
        tenant_service=TenantService(channels),
        config_service=ConfigurationService(configs),
        agent_harness=harness,
        channel_integration_ids={},
        tool_executor=tool_executors,
        onboarding_service=TenantOnboardingService(
            engine,
            checks=default_preflight_checks(
                engine,
                secrets=ResolvableSecretReferences(EnvironmentSecretResolver(environ)),
            ),
            packages_dir=packages_dir,
        ),
        tenant_packages_dir=packages_dir,
    )


class RuntimeLabMcpDiscoverer:
    """Lists tool names from an operator-provided lab MCP URL.

    Validates and allowlists the URL, then calls `tools/list` without
    intersecting a predeclared allowlist and without inventing auth.
    Client and network failures propagate (TimeoutError, OSError, DomainError).
    """

    async def list_names(self, endpoint: str) -> tuple[str, ...]:
        entry = allowlist_entry_for(endpoint)
        client = SseMcpClient(allowlist=HostAllowlist((entry,)))
        target = McpTarget(
            server_id="lab",
            allowed_tools=frozenset(),
            endpoint=endpoint.strip(),
            auth_reference="",
        )
        catalog = await client.list_tools(
            _LAB_DISCOVERY_TENANT, target, intersect_allowed=False
        )
        return tuple(tool.name for tool in catalog.tools)


def attach_runtime(app: FastAPI, runtime: RuntimeGraph) -> None:
    """Publish the graph under the names the routers already read."""
    app.state.tenant_service = runtime.tenant_service
    app.state.config_service = runtime.config_service
    app.state.agent_harness = runtime.agent_harness
    app.state.channel_integration_ids = runtime.channel_integration_ids
    app.state.tool_executor = runtime.tool_executor
    app.state.onboarding_service = runtime.onboarding_service
    app.state.tenant_packages_dir = runtime.tenant_packages_dir
    app.state.lab_mcp_discoverer = RuntimeLabMcpDiscoverer()


def runtime_lifespan(
    runtime: RuntimeGraph,
) -> Callable[[FastAPI], AbstractAsyncContextManager[None]]:
    """Load the channel integration ids on startup and release the engine."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        del app
        runtime.channel_integration_ids.update(await runtime.channels.integration_ids())
        try:
            yield
        finally:
            await runtime.engine.dispose()

    return lifespan
