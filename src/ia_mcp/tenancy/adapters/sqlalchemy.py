"""SQL lookups for tenant-scoped channel and MCP integrations.

`channel_integration.id` exists in SQL but not in the `ChannelIntegration`
contract, so the `(channel, account_id) -> id` map the simulated router needs is
read here instead of widening that dataclass. MCP targets are resolved from the
same tenant records: the server the tenant declared, the tools it declared for
that server and the credential *reference*, never a credential value.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import Row, select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from ia_mcp.configuration.adapters.sqlalchemy import (
    channel_integration_table,
    tenant_table,
)
from ia_mcp.mcp.executor import McpTarget
from ia_mcp.onboarding.service import integration_table
from ia_mcp.shared.errors import TenantIsolationViolation
from ia_mcp.tenancy.models import ChannelIntegration, TenantContext

ACTIVE = "active"
MCP_KIND = "mcp"

# A tenant without a usable MCP record resolves to a target that authorizes
# nothing: the executor denies before any transport call.
UNRESOLVED = McpTarget(server_id="", allowed_tools=frozenset(), endpoint="")


class SqlAlchemyChannelIntegrationRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self._session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def get(self, channel: str, account_id: str) -> ChannelIntegration | None:
        async with self._session_factory() as session:
            row = (
                await session.execute(
                    select(
                        channel_integration_table.c.tenant_id,
                        channel_integration_table.c.status,
                        tenant_table.c.slug,
                        tenant_table.c.status.label("tenant_status"),
                    )
                    .select_from(
                        channel_integration_table.join(
                            tenant_table,
                            tenant_table.c.id == channel_integration_table.c.tenant_id,
                        )
                    )
                    .where(
                        channel_integration_table.c.channel == channel,
                        channel_integration_table.c.external_account_id == account_id,
                    )
                )
            ).first()
        if row is None:
            return None
        enabled = row.status == ACTIVE and row.tenant_status == ACTIVE
        return ChannelIntegration(
            tenant_id=row.tenant_id,
            tenant_slug=str(row.slug),
            enabled=bool(enabled),
        )

    async def integration_ids(self) -> dict[tuple[str, str], UUID]:
        async with self._session_factory() as session:
            rows = (
                await session.execute(
                    select(
                        channel_integration_table.c.channel,
                        channel_integration_table.c.external_account_id,
                        channel_integration_table.c.id,
                    ).where(channel_integration_table.c.status == ACTIVE)
                )
            ).all()
        return {
            (str(row.channel), str(row.external_account_id)): row.id for row in rows
        }


class SqlAlchemyMcpIntegrations:
    """Tenant MCP records: declared tool catalog and resolved target.

    Endpoints are deployment data keyed by the `server_id` the tenant declared;
    a server without a configured endpoint resolves to an empty endpoint, which
    the host allowlist refuses.
    """

    def __init__(
        self, engine: AsyncEngine, *, endpoints: Mapping[str, str] | None = None
    ) -> None:
        self._session_factory = async_sessionmaker(engine, expire_on_commit=False)
        self._endpoints = dict(endpoints or {})

    async def declared_tools(self, tenant: TenantContext) -> frozenset[str]:
        return frozenset(
            tool for row in await self._records(tenant) for tool in _tools(row)
        )

    async def resolve(self, tenant: TenantContext, capability: str) -> McpTarget:
        prefix = f"{capability}."
        for row in await self._records(tenant):
            tools = _tools(row)
            if not any(
                tool == capability or tool.startswith(prefix) for tool in tools
            ):
                continue
            server_id = str(row.server_id or "")
            return McpTarget(
                server_id=server_id,
                allowed_tools=tools,
                endpoint=self._endpoints.get(server_id, ""),
                auth_reference=str(row.credentials_reference or ""),
            )
        return UNRESOLVED

    async def _records(self, tenant: TenantContext) -> Sequence[Row[Any]]:
        async with self._session_factory() as session:
            slug = (
                await session.execute(
                    select(tenant_table.c.slug).where(
                        tenant_table.c.id == tenant.tenant_id
                    )
                )
            ).scalar_one_or_none()
            if slug is None:
                return ()
            if str(slug) != tenant.tenant_slug:
                raise TenantIsolationViolation()
            return (
                await session.execute(
                    select(
                        integration_table.c.server_id,
                        integration_table.c.credentials_reference,
                        integration_table.c.capabilities,
                    )
                    .where(
                        integration_table.c.tenant_id == tenant.tenant_id,
                        integration_table.c.kind == MCP_KIND,
                        integration_table.c.status == ACTIVE,
                    )
                    .order_by(integration_table.c.server_id)
                )
            ).all()


def _tools(row: Row[Any]) -> frozenset[str]:
    declared = row.capabilities
    if not isinstance(declared, list):
        return frozenset()
    return frozenset(str(name) for name in declared if name)
