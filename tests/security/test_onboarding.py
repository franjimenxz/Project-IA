from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic.config import Config
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from alembic import command
from ia_mcp.configuration.adapters.sqlalchemy import audit_event_table, tenant_table
from ia_mcp.configuration.models import TenantAdminContext
from ia_mcp.onboarding.api import create_onboarding_router
from ia_mcp.onboarding.commands import OnboardingError, Principal
from ia_mcp.onboarding.loader import load_package
from ia_mcp.onboarding.models import (
    IntegrationsDocument,
    KnowledgeManifest,
    PackageConfig,
    PackageEvalCase,
    PolicyDocument,
    TenantDocument,
    TenantPackage,
)
from ia_mcp.onboarding.preflight import PREFLIGHT_CHECK_NAMES, CheckOutcome
from ia_mcp.onboarding.service import TenantOnboardingService, tenant_context_for
from ia_mcp.onboarding.validator import validate_package
from ia_mcp.tenancy.models import TenantContext
from tests.fixtures.admin_auth import admin_authenticator, bearer
from tests.fixtures.database import DATABASE_URL
from tests.unit.onboarding.helpers import write_package

ROOT = Path(__file__).resolve().parents[2]

TOKEN = "svctest-onboarding-security-token"

PLATFORM = Principal(
    principal_id=UUID("11111111-1111-1111-1111-111111111111"),
    roles=frozenset({"platform_admin"}),
)
OPERATOR = Principal(
    principal_id=UUID("99999999-9999-9999-9999-999999999999"),
    roles=frozenset({"operator"}),
)
AUDITOR = Principal(
    principal_id=UUID("88888888-8888-8888-8888-888888888888"),
    roles=frozenset({"auditor"}),
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


def _package(root: Path, slug: str, account: str) -> TenantPackage:
    evals = [
        {
            "case_id": f"{slug}-faq-001",
            "tenant_fixture": slug,
            "config_version": 1,
            "expected_skill": "faq",
            "allowed_tools": [],
            "forbidden_tools": ["appointments.create"],
            "messages": [{"role": "user", "text": "horario sucursal norte"}],
        }
    ]
    write_package(
        root,
        tenant={"slug": slug, "display_name": f"{slug} synthetic"},
        config={"knowledge": {"namespace": slug}, "mcp": {"server_id": f"fake-{slug}"}},
        integrations={
            "channels": [
                {
                    "channel": "simulated",
                    "external_account_id": account,
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
        evals=evals,
    )
    report = validate_package(root)
    assert report.valid is True
    loaded = load_package(root)
    return TenantPackage(
        tenant=TenantDocument.model_validate(loaded.tenant),
        config=PackageConfig.model_validate(loaded.config),
        policies=tuple(
            PolicyDocument.model_validate(body) for body in loaded.policies.values()
        ),
        knowledge=KnowledgeManifest.model_validate(loaded.knowledge),
        evals=tuple(PackageEvalCase.model_validate(row) for row in loaded.evals),
        integrations=IntegrationsDocument.model_validate(loaded.integrations),
    )


@pytest.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    _reset_schema()
    db = create_async_engine(DATABASE_URL)
    try:
        yield db
    finally:
        await db.dispose()


@pytest.mark.anyio
@pytest.mark.security
async def test_operator_cannot_provision_or_disable(
    tmp_path: Path, engine: AsyncEngine
) -> None:
    service = TenantOnboardingService(engine)
    package = _package(tmp_path / "b", "tenant-b", "tenant-b-simulated")
    with pytest.raises(OnboardingError) as provision_denied:
        await service.provision(package, OPERATOR)
    assert provision_denied.value.code == "forbidden"
    provisioned = await service.provision(package, PLATFORM)
    admin = TenantAdminContext(
        identity=provisioned.identity,
        principal_id=OPERATOR.principal_id,
        roles=OPERATOR.roles,
        correlation_id=uuid4(),
    )
    with pytest.raises(OnboardingError) as disable_denied:
        await service.disable(admin, "should-not-work")
    assert disable_denied.value.code == "forbidden"
    async with engine.connect() as connection:
        status = await connection.scalar(
            select(tenant_table.c.status).where(
                tenant_table.c.id == provisioned.identity.tenant_id
            )
        )
        audits = (
            await connection.execute(
                select(audit_event_table.c.action, audit_event_table.c.actor_id).where(
                    audit_event_table.c.tenant_id == provisioned.identity.tenant_id
                )
            )
        ).all()
    assert status == "disabled"
    assert ("provision", PLATFORM.principal_id) in set(audits)
    assert ("disable", OPERATOR.principal_id) not in set(audits)


@pytest.mark.anyio
@pytest.mark.security
async def test_tenant_admin_cannot_disable_another_tenant(
    tmp_path: Path, engine: AsyncEngine
) -> None:
    service = TenantOnboardingService(engine)
    tenant_b = await service.provision(
        _package(tmp_path / "b", "tenant-b", "tenant-b-simulated"), PLATFORM
    )
    assert tenant_b.identity.tenant_slug == "tenant-b"
    tenant_c = await service.provision(
        _package(tmp_path / "c", "tenant-c", "tenant-c-simulated"), PLATFORM
    )
    client = _admin_app(
        service,
        Principal(
            principal_id=uuid4(),
            roles=frozenset({"tenant_admin"}),
            tenant_id=tenant_b.identity.tenant_id,
            tenant_slug=tenant_b.identity.tenant_slug,
        ),
    )
    leaked = client.get("/v1/admin/tenants/tenant-c")
    assert leaked.status_code in {403, 404}
    assert "tenant-c" not in leaked.text or leaked.status_code != 200
    cross = client.post(
        "/v1/admin/tenants/tenant-c/disable",
        json={"reason": "cross-tenant"},
    )
    assert cross.status_code in {403, 404}
    own_get = client.get("/v1/admin/tenants/tenant-b")
    assert own_get.status_code == 200
    own = client.post(
        "/v1/admin/tenants/tenant-b/disable",
        json={"reason": "owner-hold"},
    )
    assert own.status_code == 200
    async with engine.connect() as connection:
        rows = (
            await connection.execute(select(tenant_table.c.slug, tenant_table.c.status))
        ).all()
        c_disable_actors = (
            (
                await connection.execute(
                    select(audit_event_table.c.actor_id).where(
                        audit_event_table.c.tenant_id == tenant_c.identity.tenant_id,
                        audit_event_table.c.action == "disable",
                    )
                )
            )
            .scalars()
            .all()
        )
        dump = str(rows)
    by_slug = {row[0]: row[1] for row in rows}
    assert by_slug["tenant-b"] == "disabled"
    assert by_slug["tenant-c"] == "disabled"
    assert c_disable_actors == []
    assert "plain-secret" not in dump
    assert "sm://tenant-b/mcp/appointments" not in dump


@pytest.mark.anyio
@pytest.mark.security
async def test_auditor_cannot_provision_and_audit_omits_secret_values(
    tmp_path: Path, engine: AsyncEngine
) -> None:
    service = TenantOnboardingService(engine)
    package = _package(tmp_path / "b", "tenant-b", "tenant-b-simulated")
    with pytest.raises(OnboardingError) as denied:
        await service.provision(package, AUDITOR)
    assert denied.value.code == "forbidden"
    provisioned = await service.provision(package, PLATFORM)
    async with engine.connect() as connection:
        audits = (await connection.execute(select(audit_event_table))).mappings().all()
        payload = str(audits)
    assert all(row["action"] == "provision" for row in audits)
    assert all(row["tenant_id"] == provisioned.identity.tenant_id for row in audits)
    assert "plain-secret" not in payload
    assert "sk-live" not in payload
    assert not hasattr(service, "ingest")
    assert not hasattr(service.provision, "activate")


@dataclass(frozen=True, slots=True)
class StubCheck:
    name: str
    passed: bool = True
    severity: str = "critical"
    code: str = "ok"
    message: str = "ok"

    async def run(self, tenant: TenantContext) -> CheckOutcome:
        return CheckOutcome(
            name=self.name,
            passed=self.passed,
            severity="critical",
            code=self.code,
            message=self.message,
        )


def _passing_checks() -> tuple[StubCheck, ...]:
    return tuple(StubCheck(name=name) for name in PREFLIGHT_CHECK_NAMES)


def _admin_app(service: TenantOnboardingService, principal: Principal) -> TestClient:
    """A client that presents `TOKEN`, authenticated as `principal`."""
    app = FastAPI()
    app.include_router(create_onboarding_router())
    app.state.onboarding_service = service
    app.state.admin_authenticator = admin_authenticator({TOKEN: principal})
    return TestClient(app, headers=bearer(TOKEN))


@pytest.mark.anyio
@pytest.mark.security
async def test_tenant_admin_cannot_activate_another_tenant(
    tmp_path: Path, engine: AsyncEngine
) -> None:
    service = TenantOnboardingService(engine, checks=_passing_checks())
    tenant_b = await service.provision(
        _package(tmp_path / "b", "tenant-b", "tenant-b-simulated"), PLATFORM
    )
    tenant_c = await service.provision(
        _package(tmp_path / "c", "tenant-c", "tenant-c-simulated"), PLATFORM
    )
    hash_c = validate_package(tmp_path / "c").content_hash
    assert hash_c is not None
    report_c = await service.preflight(tenant_context_for(tenant_c), content_hash=hash_c)
    client = _admin_app(
        service,
        Principal(
            principal_id=uuid4(),
            roles=frozenset({"tenant_admin"}),
            tenant_id=tenant_b.identity.tenant_id,
            tenant_slug=tenant_b.identity.tenant_slug,
        ),
    )
    leaked = client.post(
        "/v1/admin/tenants/tenant-c/activate",
        json={
            "report_hash": report_c.report_hash,
            "identity": {
                "tenant_id": str(tenant_c.identity.tenant_id),
                "tenant_slug": tenant_c.identity.tenant_slug,
            },
        },
    )
    assert leaked.status_code in {403, 404, 422}
    assert leaked.status_code != 200
    cross = client.post(
        "/v1/admin/tenants/tenant-c/activate",
        json={"report_hash": report_c.report_hash},
    )
    assert cross.status_code in {403, 404}
    assert cross.status_code != 200
    own_get = client.get("/v1/admin/tenants/tenant-b")
    assert own_get.status_code == 200
    async with engine.connect() as connection:
        rows = (
            await connection.execute(select(tenant_table.c.slug, tenant_table.c.status))
        ).all()
        c_activate_actors = (
            (
                await connection.execute(
                    select(audit_event_table.c.actor_id).where(
                        audit_event_table.c.tenant_id == tenant_c.identity.tenant_id,
                        audit_event_table.c.action == "activate",
                    )
                )
            )
            .scalars()
            .all()
        )
    by_slug = {row[0]: row[1] for row in rows}
    assert by_slug["tenant-b"] == "disabled"
    assert by_slug["tenant-c"] == "disabled"
    assert c_activate_actors == []


@pytest.mark.anyio
@pytest.mark.security
async def test_platform_admin_may_activate_and_operator_cannot(
    tmp_path: Path, engine: AsyncEngine
) -> None:
    service = TenantOnboardingService(engine, checks=_passing_checks())
    tenant_c = await service.provision(
        _package(tmp_path / "c", "tenant-c", "tenant-c-simulated"), PLATFORM
    )
    hash_c = validate_package(tmp_path / "c").content_hash
    assert hash_c is not None
    report_c = await service.preflight(tenant_context_for(tenant_c), content_hash=hash_c)
    operator_client = _admin_app(service, OPERATOR)
    denied = operator_client.post(
        "/v1/admin/tenants/tenant-c/activate",
        json={"report_hash": report_c.report_hash},
    )
    assert denied.status_code in {403, 404}
    platform_client = _admin_app(service, PLATFORM)
    activated = platform_client.post(
        "/v1/admin/tenants/tenant-c/activate",
        json={"report_hash": report_c.report_hash},
    )
    assert activated.status_code == 200
    assert activated.json()["status"] == "active"
    async with engine.connect() as connection:
        status = await connection.scalar(
            select(tenant_table.c.status).where(
                tenant_table.c.id == tenant_c.identity.tenant_id
            )
        )
        payload = await connection.scalar(
            select(audit_event_table.c.payload).where(
                audit_event_table.c.tenant_id == tenant_c.identity.tenant_id,
                audit_event_table.c.action == "activate",
            )
        )
    assert status == "active"
    assert "plain-secret" not in str(payload)
    assert isinstance(payload, dict)
    assert payload.get("report_hash") == report_c.report_hash
