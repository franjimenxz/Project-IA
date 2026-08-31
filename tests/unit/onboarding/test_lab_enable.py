"""lab_enable contract (AC-P13-003).

No PostgreSQL: the service checks the process environment before touching
storage, and the store collaborator is replaced with an in-memory double that
records channels, status and the config version `capture()` would read.
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from ia_mcp.configuration.models import (
    AgentConfig,
    TenantAdminContext,
    TenantConfig,
)
from ia_mcp.configuration.service import ConfigurationService
from ia_mcp.onboarding.commands import OnboardingError, ProvisionedTenant
from ia_mcp.onboarding.service import PLATFORM_ADMIN, TenantOnboardingService
from ia_mcp.tenancy.models import TenantIdentity

UNREACHABLE_DATABASE_URL = "postgresql+psycopg://ia_mcp@127.0.0.1:1/ia_mcp_lab_enable"
TENANT_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
PRINCIPAL_ID = UUID("11111111-1111-1111-1111-111111111111")
SLUG = "clinica-norte"


def _run[T](coro: Coroutine[object, object, T]) -> T:
    return asyncio.run(coro)


def _admin(*, roles: frozenset[str] = frozenset({PLATFORM_ADMIN})) -> TenantAdminContext:
    return TenantAdminContext(
        identity=TenantIdentity(tenant_id=TENANT_ID, tenant_slug=SLUG),
        principal_id=PRINCIPAL_ID,
        roles=roles,
        correlation_id=uuid4(),
    )


def _service() -> TenantOnboardingService:
    return TenantOnboardingService(create_async_engine(UNREACHABLE_DATABASE_URL))


@dataclass
class _Channel:
    channel: str
    status: str


@dataclass
class _MemoryLabStore:
    """Records lab_enable mutations the way the SQL store must behave."""

    status: str = "disabled"
    config_version: int = 1
    config_status: str = "draft"
    active_config_version: int | None = None
    channels: list[_Channel] = field(
        default_factory=lambda: [_Channel(channel="simulated", status="disabled")]
    )
    audits: list[str] = field(default_factory=list)
    payload: dict[str, Any] = field(
        default_factory=lambda: {
            "schema_version": 1,
            "agent": {"tone": "formal"},
            "enabled_skills": [],
            "enabled_tools": [],
        }
    )

    async def lab_enable(self, admin: TenantAdminContext) -> ProvisionedTenant:
        if self.active_config_version is None:
            self.active_config_version = self.config_version
        if self.config_status == "draft":
            self.config_status = "published"
        self.status = "active"
        for channel in self.channels:
            if channel.channel == "simulated":
                channel.status = "active"
        self.audits.append("lab_enable")
        return ProvisionedTenant(
            identity=admin.identity,
            status="active",
            config_version=self.config_version,
            config_status=self.config_status,  # type: ignore[arg-type]
        )


class _MemoryConfigRepo:
    def __init__(self, store: _MemoryLabStore) -> None:
        self._store = store

    async def get_active(self, identity: TenantIdentity) -> TenantConfig | None:
        if self._store.active_config_version is None:
            return None
        if identity.tenant_id != TENANT_ID or identity.tenant_slug != SLUG:
            return None
        return TenantConfig(
            tenant_id=identity.tenant_id,
            version=int(self._store.active_config_version),
            agent=AgentConfig(tone="formal"),
        )

    async def publish(self, admin: TenantAdminContext, draft: object) -> TenantConfig:
        del admin, draft
        raise AssertionError("publish is not part of lab_enable")

    async def activate(self, admin: TenantAdminContext, version: int) -> None:
        del admin, version
        raise AssertionError("activate is not part of lab_enable")

    async def get_version(self, identity: TenantIdentity, version: int) -> TenantConfig | None:
        del identity, version
        return None

    async def get_for_runtime(self, context: object) -> TenantConfig | None:
        del context
        return None

    async def record_audit(
        self, admin: TenantAdminContext, action: str, version: int
    ) -> None:
        del admin, action, version


def test_lab_enable_rejects_production(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IA_MCP_ENVIRONMENT", "production")
    service = _service()
    with pytest.raises(OnboardingError) as refused:
        _run(service.lab_enable(_admin()))
    assert refused.value.code == "lab_unavailable"
    assert "available" in refused.value.safe_message.lower()


def test_lab_enable_is_idempotent_and_enables_capture(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("IA_MCP_ENVIRONMENT", "test")
    service = _service()
    store = _MemoryLabStore()
    service._store = store  # type: ignore[method-assign]
    admin = _admin()
    first = _run(service.lab_enable(admin))
    second = _run(service.lab_enable(admin))
    simulated = [item for item in store.channels if item.channel == "simulated"]
    assert first.status == "active"
    assert second.status == "active"
    assert len(simulated) == 1
    assert simulated[0].status == "active"
    assert store.audits == ["lab_enable", "lab_enable"]
    captured = _run(
        ConfigurationService(_MemoryConfigRepo(store)).capture(admin.identity, uuid4())
    )
    context, config = captured
    assert context.tenant_id == TENANT_ID
    assert context.tenant_slug == SLUG
    assert config.version == 1


def test_lab_enable_requires_platform_admin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IA_MCP_ENVIRONMENT", "development")
    service = _service()
    service._store = _MemoryLabStore()  # type: ignore[method-assign]
    operator = _admin(roles=frozenset({"operator"}))
    with pytest.raises(OnboardingError) as refused:
        _run(service.lab_enable(operator))
    assert refused.value.code == "forbidden"


def test_list_tenants_is_on_the_service() -> None:
    service = _service()
    assert hasattr(service, "list_tenants")
    assert asyncio.iscoroutinefunction(service.list_tenants)
