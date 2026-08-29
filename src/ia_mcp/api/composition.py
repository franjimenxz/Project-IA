"""Runtime composition root.

Builds the collaborator graph the HTTP process needs to run a turn and hands it
to `create_app`. It only constructs and connects existing collaborators: no
domain rule, no tenant branch and no credential value lives here.

Development reads three variables:

- `DATABASE_URL`, already used by `ia_mcp.onboarding.cli`.
- `IA_MCP_MCP_ENDPOINTS`, an optional `server_id=endpoint` list (comma
  separated) that maps the MCP servers tenants declared to the addresses this
  deployment may reach. It is the only source of MCP hosts, and the host
  allowlist is derived from it, so no host is hardcoded in Core. Without it
  there is no generic MCP transport at all.
- `IA_MCP_TENANT_PACKAGES_DIR`, an optional absolute directory the onboarding
  HTTP boundary may read tenant packages from. It is the only root that
  boundary accepts, so without it every request naming a `package_path` is
  refused. The CLI is unaffected: an operator keeps passing local paths.
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
from ia_mcp.agent_runtime.ports import FakeLLM
from ia_mcp.agent_runtime.run_repository import SqlAlchemyAgentRunRepository
from ia_mcp.configuration.adapters.sqlalchemy import SqlAlchemyConfigRepository
from ia_mcp.configuration.models import TenantConfig
from ia_mcp.configuration.service import ConfigurationService
from ia_mcp.conversation.adapters.sqlalchemy import SqlAlchemyConversationRepository
from ia_mcp.knowledge.models import KnowledgeHit, KnowledgeQuery
from ia_mcp.mcp.capabilities.appointments import AppointmentCapability
from ia_mcp.mcp.client import SseMcpClient
from ia_mcp.mcp.executor import (
    HostAllowlist,
    McpTarget,
    McpTransportClient,
    ToolExecutor,
)
from ia_mcp.mcp.fakes.appointments import FakeAppointmentCapability
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


class TenantToolExecutors:
    """Builds a `ToolExecutor` for one tenant.

    The three allowlists an executor intersects are tenant data (the server
    catalog the tenant declared, its enabled tools and the active skill), so the
    composition root exposes this factory instead of one shared executor that
    could not be tenant-scoped.
    """

    def __init__(
        self,
        *,
        integrations: TenantMcpIntegrations,
        capability: AppointmentCapability,
        skills: SkillRegistry,
        allowed_hosts: Iterable[str] = (),
        transport: McpTransportClient | None = None,
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
        self.allowed_hosts = hosts
        self.transport = transport

    async def for_tenant(
        self, tenant: TenantContext, config: TenantConfig, skill: str
    ) -> ToolExecutor:
        return ToolExecutor(
            server=await self._integrations.declared_tools(tenant),
            tenant=config.enabled_tools,
            skill=self._skills.resolve(skill, config).allowed_tools(config),
            capability=self._capability,
            resolver=self._integrations,
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
    endpoints = mcp_endpoints_from(environ)
    hosts = allowed_hosts_for(endpoints)
    transport = SseMcpClient(allowlist=HostAllowlist(hosts)) if hosts else None
    harness = AgentHarness(
        conversations=SqlAlchemyConversationRepository(engine),
        runs=SqlAlchemyAgentRunRepository(engine),
        configs=configs,
        skills=skills,
        compiler=ContextCompiler(configs=configs, skills=skills, tenant_tools={}),
        knowledge=EmptyKnowledgeSearch(),
        llm=FakeLLM(LLMDecision(kind="insufficient", text="", source_ids=())),
    )
    return RuntimeGraph(
        engine=engine,
        channels=channels,
        tenant_service=TenantService(channels),
        config_service=ConfigurationService(configs),
        agent_harness=harness,
        channel_integration_ids={},
        tool_executor=TenantToolExecutors(
            integrations=SqlAlchemyMcpIntegrations(engine, endpoints=endpoints),
            capability=FakeAppointmentCapability(),
            skills=skills,
            allowed_hosts=hosts,
            transport=transport,
        ),
        onboarding_service=TenantOnboardingService(engine),
        tenant_packages_dir=tenant_packages_dir_from(environ),
    )


def attach_runtime(app: FastAPI, runtime: RuntimeGraph) -> None:
    """Publish the graph under the names the routers already read."""
    app.state.tenant_service = runtime.tenant_service
    app.state.config_service = runtime.config_service
    app.state.agent_harness = runtime.agent_harness
    app.state.channel_integration_ids = runtime.channel_integration_ids
    app.state.tool_executor = runtime.tool_executor
    app.state.onboarding_service = runtime.onboarding_service
    app.state.tenant_packages_dir = runtime.tenant_packages_dir


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
