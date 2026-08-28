from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from alembic import command
from ia_mcp.configuration.adapters.sqlalchemy import (
    SqlAlchemyConfigRepository,
    audit_event_table,
    channel_integration_table,
    tenant_table,
)
from ia_mcp.configuration.models import (
    AgentConfig,
    TenantAdminContext,
    TenantConfigDraft,
)
from ia_mcp.configuration.service import ConfigurationService
from ia_mcp.onboarding.commands import OnboardingError, Principal, load_tenant_package
from ia_mcp.onboarding.preflight import (
    PREFLIGHT_CHECK_NAMES,
    CheckOutcome,
    PreflightCheckPort,
    PreflightReport,
)
from ia_mcp.onboarding.service import TenantOnboardingService, tenant_context_for
from ia_mcp.onboarding.validator import validate_package
from ia_mcp.shared.errors import TenantIsolationViolation
from ia_mcp.tenancy.models import TenantContext
from ia_mcp.tenancy.service import TenantResolutionError, TenantService
from tests.unit.onboarding.helpers import write_package

ROOT = Path(__file__).resolve().parents[3]
DATABASE_URL = "postgresql+psycopg://francojimenez@127.0.0.1:5432/ia_mcp_p02_t03"

PLATFORM = Principal(
    principal_id=UUID("11111111-1111-1111-1111-111111111111"),
    roles=frozenset({"platform_admin"}),
)


@dataclass(frozen=True, slots=True)
class StubCheck:
    name: str
    passed: bool = True
    severity: str = "critical"
    code: str = "ok"
    message: str = "ok"

    async def run(self, tenant: TenantContext) -> CheckOutcome:
        if tenant.tenant_id is None:
            raise TenantIsolationViolation()
        return CheckOutcome(
            name=self.name,
            passed=self.passed,
            severity="critical" if self.severity == "critical" else "warning",
            code=self.code,
            message=self.message,
        )


def _reset_schema() -> None:
    engine = create_engine(DATABASE_URL)
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))
    engine.dispose()
    alembic_cfg = Config(str(ROOT / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(ROOT / "alembic"))
    alembic_cfg.set_main_option("sqlalchemy.url", DATABASE_URL)
    command.upgrade(alembic_cfg, "head")


def _package_root(root: Path, slug: str = "tenant-b") -> Path:
    return write_package(
        root,
        tenant={"slug": slug, "display_name": f"{slug} synthetic"},
        config={"knowledge": {"namespace": slug}, "mcp": {"server_id": f"fake-{slug}"}},
        integrations={
            "channels": [
                {
                    "channel": "simulated",
                    "external_account_id": f"{slug}-simulated",
                    "secret_reference": f"sm://{slug}/channel/simulated",
                }
            ],
            "integrations": [
                {
                    "kind": "mcp",
                    "server_id": f"fake-{slug}",
                    "credentials_reference": f"sm://{slug}/mcp/appointments",
                    "capabilities": [
                        "appointments.search",
                        "appointments.get",
                        "appointments.create",
                    ],
                }
            ],
        },
        knowledge={"namespace": slug},
    )


def stub_checks(*, fail: str | None = None) -> tuple[StubCheck, ...]:
    return tuple(
        StubCheck(
            name=name,
            passed=name != fail,
            code="check_failed" if name == fail else "ok",
            message="unpublished knowledge" if name == fail else "ok",
        )
        for name in PREFLIGHT_CHECK_NAMES
    )


def _service(
    engine: AsyncEngine, checks: Sequence[PreflightCheckPort] | None = None
) -> TenantOnboardingService:
    return TenantOnboardingService(engine, checks=checks or stub_checks())


@pytest.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    _reset_schema()
    db = create_async_engine(DATABASE_URL)
    try:
        yield db
    finally:
        await db.dispose()


@pytest.mark.anyio
@pytest.mark.integration
async def test_stale_report_hash_cannot_activate_changed_package(
    tmp_path: Path, engine: AsyncEngine
) -> None:
    service = _service(engine)
    root = _package_root(tmp_path / "b")
    package = load_tenant_package(root)
    h1 = validate_package(root).content_hash
    assert h1 is not None
    provisioned = await service.provision(package, PLATFORM)
    tenant = tenant_context_for(provisioned)
    report_h1 = await service.preflight(tenant, content_hash=h1)
    assert isinstance(report_h1, PreflightReport)
    assert report_h1.passed is True
    assert report_h1.content_hash == h1

    write_package(
        root,
        tenant={"slug": "tenant-b", "display_name": "tenant-b synthetic"},
        config={
            "knowledge": {"namespace": "tenant-b"},
            "mcp": {"server_id": "fake-tenant-b"},
            "agent": {"tone": "cordial"},
        },
        integrations={
            "channels": [
                {
                    "channel": "simulated",
                    "external_account_id": "tenant-b-simulated",
                    "secret_reference": "sm://tenant-b/channel/simulated-v2",
                }
            ],
            "integrations": [
                {
                    "kind": "mcp",
                    "server_id": "fake-tenant-b",
                    "credentials_reference": "sm://tenant-b/mcp/appointments",
                    "capabilities": [
                        "appointments.search",
                        "appointments.get",
                        "appointments.create",
                    ],
                }
            ],
        },
        knowledge={"namespace": "tenant-b"},
    )
    h2 = validate_package(root).content_hash
    assert h2 is not None
    assert h1 != h2
    report_h2 = await service.preflight(tenant, content_hash=h2)
    assert report_h2.content_hash == h2
    assert report_h1.report_hash != report_h2.report_hash

    admin = TenantAdminContext(
        identity=provisioned.identity,
        principal_id=PLATFORM.principal_id,
        roles=PLATFORM.roles,
        correlation_id=uuid4(),
    )
    with pytest.raises(OnboardingError) as stale:
        await service.activate(admin, report_h1.report_hash)
    assert stale.value.code == "stale_preflight"
    async with engine.connect() as connection:
        status = await connection.scalar(
            select(tenant_table.c.status).where(
                tenant_table.c.id == provisioned.identity.tenant_id
            )
        )
        mapping_status = await connection.scalar(
            select(channel_integration_table.c.status).where(
                channel_integration_table.c.tenant_id == provisioned.identity.tenant_id
            )
        )
    assert status == "disabled"
    assert mapping_status == "disabled"


@pytest.mark.anyio
@pytest.mark.integration
async def test_stale_config_hash_cannot_activate(
    tmp_path: Path, engine: AsyncEngine
) -> None:
    service = _service(engine)
    root = _package_root(tmp_path / "b")
    h1 = validate_package(root).content_hash
    assert h1 is not None
    provisioned = await service.provision(load_tenant_package(root), PLATFORM)
    report = await service.preflight(tenant_context_for(provisioned), content_hash=h1)
    admin = TenantAdminContext(
        identity=provisioned.identity,
        principal_id=PLATFORM.principal_id,
        roles=PLATFORM.roles,
        correlation_id=uuid4(),
    )
    config_service = ConfigurationService(SqlAlchemyConfigRepository(engine))
    await config_service.publish(
        admin, TenantConfigDraft(agent=AgentConfig(tone="cordial"))
    )
    with pytest.raises(OnboardingError) as stale:
        await service.activate(admin, report.report_hash)
    assert stale.value.code == "stale_preflight"


@pytest.mark.anyio
@pytest.mark.integration
async def test_failed_check_cannot_activate_and_has_no_critical_waiver(
    tmp_path: Path, engine: AsyncEngine
) -> None:
    service = _service(engine, checks=stub_checks(fail="retrieval_canary"))
    root = _package_root(tmp_path / "b")
    h1 = validate_package(root).content_hash
    assert h1 is not None
    provisioned = await service.provision(load_tenant_package(root), PLATFORM)
    report = await service.preflight(tenant_context_for(provisioned), content_hash=h1)
    assert report.passed is False
    assert any(
        item.name == "retrieval_canary" and item.passed is False
        for item in report.checks
    )
    admin = TenantAdminContext(
        identity=provisioned.identity,
        principal_id=PLATFORM.principal_id,
        roles=PLATFORM.roles,
        correlation_id=uuid4(),
    )
    with pytest.raises(OnboardingError) as denied:
        await service.activate(admin, report.report_hash)
    assert denied.value.code == "preflight_failed"
    assert "waiver" not in TenantOnboardingService.activate.__code__.co_varnames
    async with engine.connect() as connection:
        status = await connection.scalar(
            select(tenant_table.c.status).where(
                tenant_table.c.id == provisioned.identity.tenant_id
            )
        )
    assert status == "disabled"


@pytest.mark.anyio
@pytest.mark.integration
async def test_preflight_and_activate_are_idempotent(
    tmp_path: Path, engine: AsyncEngine
) -> None:
    service = _service(engine)
    root = _package_root(tmp_path / "b")
    h1 = validate_package(root).content_hash
    assert h1 is not None
    provisioned = await service.provision(load_tenant_package(root), PLATFORM)
    tenant = tenant_context_for(provisioned)
    first = await service.preflight(tenant, content_hash=h1)
    second = await service.preflight(tenant, content_hash=h1)
    assert first.report_hash == second.report_hash
    admin = TenantAdminContext(
        identity=provisioned.identity,
        principal_id=PLATFORM.principal_id,
        roles=PLATFORM.roles,
        correlation_id=uuid4(),
    )
    await service.activate(admin, first.report_hash)
    await service.activate(admin, first.report_hash)
    resolver = TenantService(service)
    identity = await resolver.resolve("simulated", "tenant-b-simulated")
    assert identity.tenant_id == provisioned.identity.tenant_id
    async with engine.connect() as connection:
        tenants = await connection.scalar(
            select(func.count()).select_from(tenant_table)
        )
        mappings = await connection.scalar(
            select(func.count()).select_from(channel_integration_table)
        )
        activate_audits = list(
            (
                await connection.execute(
                    select(audit_event_table.c.action).where(
                        audit_event_table.c.tenant_id == provisioned.identity.tenant_id,
                        audit_event_table.c.action == "activate",
                    )
                )
            )
            .scalars()
            .all()
        )
        status = await connection.scalar(
            select(tenant_table.c.status).where(
                tenant_table.c.id == provisioned.identity.tenant_id
            )
        )
        active_version = await connection.scalar(
            select(tenant_table.c.active_config_version).where(
                tenant_table.c.id == provisioned.identity.tenant_id
            )
        )
        payload = await connection.scalar(
            select(audit_event_table.c.payload).where(
                audit_event_table.c.tenant_id == provisioned.identity.tenant_id,
                audit_event_table.c.action == "activate",
            )
        )
    assert int(tenants or 0) == 1
    assert int(mappings or 0) == 1
    assert status == "active"
    assert active_version == 1
    assert len(activate_audits) == 1
    assert "plain-secret" not in str(payload)
    assert isinstance(payload, dict)
    assert payload.get("report_hash") == first.report_hash


@pytest.mark.anyio
@pytest.mark.integration
async def test_preflight_fails_closed_when_required_check_missing(
    tmp_path: Path, engine: AsyncEngine
) -> None:
    service = _service(engine, checks=stub_checks()[:-1])
    root = _package_root(tmp_path / "b")
    h1 = validate_package(root).content_hash
    assert h1 is not None
    provisioned = await service.provision(load_tenant_package(root), PLATFORM)
    report = await service.preflight(tenant_context_for(provisioned), content_hash=h1)
    assert report.passed is False
    assert any(item.code == "missing_check" for item in report.checks)


@pytest.mark.anyio
@pytest.mark.integration
async def test_preflight_requires_matching_tenant_context(
    tmp_path: Path, engine: AsyncEngine
) -> None:
    service = _service(engine)
    root = _package_root(tmp_path / "b")
    h1 = validate_package(root).content_hash
    assert h1 is not None
    provisioned = await service.provision(load_tenant_package(root), PLATFORM)
    foreign = TenantContext(
        tenant_id=uuid4(),
        tenant_slug=provisioned.identity.tenant_slug,
        config_version=provisioned.config_version,
        correlation_id=uuid4(),
    )
    with pytest.raises(TenantIsolationViolation):
        await service.preflight(foreign, content_hash=h1)
    slug_mismatch = TenantContext(
        tenant_id=provisioned.identity.tenant_id,
        tenant_slug="tenant-c",
        config_version=provisioned.config_version,
        correlation_id=uuid4(),
    )
    with pytest.raises(TenantIsolationViolation):
        await service.preflight(slug_mismatch, content_hash=h1)


@pytest.mark.anyio
@pytest.mark.integration
async def test_activate_enables_channel_then_disable_blocks_resolve(
    tmp_path: Path, engine: AsyncEngine
) -> None:
    service = _service(engine)
    root = _package_root(tmp_path / "b")
    h1 = validate_package(root).content_hash
    assert h1 is not None
    provisioned = await service.provision(load_tenant_package(root), PLATFORM)
    report = await service.preflight(tenant_context_for(provisioned), content_hash=h1)
    admin = TenantAdminContext(
        identity=provisioned.identity,
        principal_id=PLATFORM.principal_id,
        roles=PLATFORM.roles,
        correlation_id=uuid4(),
    )
    resolver = TenantService(service)
    with pytest.raises(TenantResolutionError) as before:
        await resolver.resolve("simulated", "tenant-b-simulated")
    assert before.value.code == "disabled_channel_account"
    await service.activate(admin, report.report_hash)
    resolved = await resolver.resolve("simulated", "tenant-b-simulated")
    assert resolved.tenant_slug == "tenant-b"
    await service.disable(admin, "cutover-hold")
    with pytest.raises(TenantResolutionError) as after:
        await resolver.resolve("simulated", "tenant-b-simulated")
    assert after.value.code == "disabled_channel_account"
