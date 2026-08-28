from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from alembic import command
from ia_mcp.configuration.adapters.sqlalchemy import audit_event_table, tenant_table
from ia_mcp.configuration.models import TenantAdminContext
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
from ia_mcp.onboarding.service import TenantOnboardingService
from ia_mcp.onboarding.validator import validate_package
from ia_mcp.shared.errors import TenantIsolationViolation
from ia_mcp.tenancy.models import TenantIdentity
from tests.unit.onboarding.helpers import write_package

ROOT = Path(__file__).resolve().parents[2]
DATABASE_URL = "postgresql+psycopg://francojimenez@127.0.0.1:5432/ia_mcp_p02_t03"

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
    foreign_admin = TenantAdminContext(
        identity=TenantIdentity(
            tenant_id=tenant_c.identity.tenant_id,
            tenant_slug="tenant-b",
        ),
        principal_id=uuid4(),
        roles=frozenset({"tenant_admin"}),
        correlation_id=uuid4(),
    )
    with pytest.raises(TenantIsolationViolation):
        await service.disable(foreign_admin, "cross-tenant")
    own_admin = TenantAdminContext(
        identity=tenant_c.identity,
        principal_id=uuid4(),
        roles=frozenset({"tenant_admin"}),
        correlation_id=uuid4(),
    )
    await service.disable(own_admin, "owner-hold")
    async with engine.connect() as connection:
        rows = (
            await connection.execute(select(tenant_table.c.slug, tenant_table.c.status))
        ).all()
        dump = str(rows)
    by_slug = {row[0]: row[1] for row in rows}
    assert by_slug["tenant-b"] == "disabled"
    assert by_slug["tenant-c"] == "disabled"
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
