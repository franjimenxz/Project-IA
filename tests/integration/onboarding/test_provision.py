from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic.config import Config
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from alembic import command
from ia_mcp.configuration.adapters.sqlalchemy import (
    SqlAlchemyConfigRepository,
    audit_event_table,
    channel_integration_table,
    tenant_config_table,
    tenant_table,
)
from ia_mcp.configuration.models import (
    AgentConfig,
    TenantAdminContext,
    TenantConfigDraft,
)
from ia_mcp.configuration.service import ConfigurationService
from ia_mcp.knowledge.adapters.sqlalchemy import knowledge_document_table
from ia_mcp.onboarding.api import create_onboarding_router
from ia_mcp.onboarding.cli import main as onboarding_cli
from ia_mcp.onboarding.commands import OnboardingError, Principal, load_tenant_package
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
from ia_mcp.scheduling.models import JOB_TYPE, ScheduledJob
from ia_mcp.scheduling.service import SqlAlchemyJobStore, scheduled_job_table
from ia_mcp.shared.errors import DomainError
from ia_mcp.tenancy.models import TenantIdentity
from ia_mcp.tenancy.service import TenantResolutionError, TenantService
from tests.fixtures.admin_auth import admin_authenticator, bearer
from tests.fixtures.database import DATABASE_URL
from tests.unit.onboarding.helpers import write_package

ROOT = Path(__file__).resolve().parents[3]

PLATFORM_PRINCIPAL = Principal(
    principal_id=UUID("11111111-1111-1111-1111-111111111111"),
    roles=frozenset({"platform_admin"}),
)
TOKEN = "svctest-provision-token"
TENANT_A = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
TENANT_A_IDENTITY = TenantIdentity(tenant_id=TENANT_A, tenant_slug="tenant-a")
TENANT_A_ADMIN = TenantAdminContext(
    identity=TENANT_A_IDENTITY,
    principal_id=UUID("22222222-2222-2222-2222-222222222222"),
    roles=frozenset({"tenant_admin"}),
    correlation_id=UUID("33333333-3333-3333-3333-333333333333"),
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


def _package_for(
    root: Path,
    *,
    slug: str,
    account: str,
    server_id: str,
) -> Path:
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
    return write_package(
        root,
        tenant={"slug": slug, "display_name": f"{slug} synthetic"},
        config={
            "knowledge": {"namespace": slug},
            "mcp": {"server_id": server_id},
        },
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
                    "server_id": server_id,
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


def _tenant_package(root: Path) -> TenantPackage:
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
        integrations=IntegrationsDocument.model_validate(loaded.integrations),
        evals=tuple(PackageEvalCase.model_validate(row) for row in loaded.evals),
    )


async def _count(engine: AsyncEngine, statement: object) -> int:
    async with engine.connect() as connection:
        result = await connection.scalar(statement)  # type: ignore[arg-type]
        return int(result or 0)


@pytest.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    _reset_schema()
    db = create_async_engine(DATABASE_URL)
    try:
        yield db
    finally:
        await db.dispose()


@pytest.fixture
def service(engine: AsyncEngine) -> TenantOnboardingService:
    return TenantOnboardingService(engine)


@pytest.mark.anyio
@pytest.mark.integration
async def test_replay_provision_returns_same_tenant_without_duplicate_mappings(
    tmp_path: Path,
    engine: AsyncEngine,
    service: TenantOnboardingService,
) -> None:
    root = _package_for(
        tmp_path / "b",
        slug="tenant-b",
        account="tenant-b-simulated",
        server_id="fake-appointments-b",
    )
    package = _tenant_package(root)
    first = await service.provision(package, PLATFORM_PRINCIPAL)
    second = await service.provision(package, PLATFORM_PRINCIPAL)
    assert first.identity.tenant_id == second.identity.tenant_id
    assert first.identity.tenant_slug == "tenant-b"
    assert first.status == "disabled"
    assert second.status == "disabled"
    assert first.config_status == "draft"
    tenants = await _count(engine, select(func.count()).select_from(tenant_table))
    configs = await _count(
        engine, select(func.count()).select_from(tenant_config_table)
    )
    mappings = await _count(
        engine, select(func.count()).select_from(channel_integration_table)
    )
    assert tenants == 1
    assert configs == 1
    assert mappings == 1


@pytest.mark.anyio
@pytest.mark.integration
async def test_concurrent_provision_does_not_duplicate_tenant_or_mapping(
    tmp_path: Path,
    engine: AsyncEngine,
    service: TenantOnboardingService,
) -> None:
    root = _package_for(
        tmp_path / "b",
        slug="tenant-b",
        account="tenant-b-simulated",
        server_id="fake-appointments-b",
    )
    package = _tenant_package(root)
    first, second = await asyncio.gather(
        service.provision(package, PLATFORM_PRINCIPAL),
        service.provision(package, PLATFORM_PRINCIPAL),
    )
    assert first.identity.tenant_id == second.identity.tenant_id
    tenants = await _count(engine, select(func.count()).select_from(tenant_table))
    mappings = await _count(
        engine, select(func.count()).select_from(channel_integration_table)
    )
    configs = await _count(
        engine, select(func.count()).select_from(tenant_config_table)
    )
    assert tenants == 1
    assert mappings == 1
    assert configs == 1


@pytest.mark.anyio
@pytest.mark.integration
async def test_provision_writes_disabled_draft_integration_refs_and_audit(
    tmp_path: Path,
    engine: AsyncEngine,
    service: TenantOnboardingService,
) -> None:
    root = _package_for(
        tmp_path / "b",
        slug="tenant-b",
        account="tenant-b-simulated",
        server_id="fake-appointments-b",
    )
    provisioned = await service.provision(_tenant_package(root), PLATFORM_PRINCIPAL)
    async with engine.connect() as connection:
        tenant = (
            (
                await connection.execute(
                    select(tenant_table).where(tenant_table.c.slug == "tenant-b")
                )
            )
            .mappings()
            .one()
        )
        config = (
            (
                await connection.execute(
                    select(tenant_config_table).where(
                        tenant_config_table.c.tenant_id
                        == provisioned.identity.tenant_id
                    )
                )
            )
            .mappings()
            .one()
        )
        channel = (
            (await connection.execute(select(channel_integration_table)))
            .mappings()
            .one()
        )
        integrations = (
            (
                await connection.execute(
                    text(
                        "SELECT kind, server_id, credentials_reference, status, capabilities "
                        "FROM integration WHERE tenant_id = :tenant_id"
                    ),
                    {"tenant_id": provisioned.identity.tenant_id},
                )
            )
            .mappings()
            .all()
        )
        audits = (
            (
                await connection.execute(
                    select(audit_event_table.c.action).where(
                        audit_event_table.c.tenant_id == provisioned.identity.tenant_id
                    )
                )
            )
            .scalars()
            .all()
        )
        knowledge_rows = await connection.scalar(
            select(func.count()).select_from(knowledge_document_table)
        )
    assert tenant["status"] == "disabled"
    assert tenant["active_config_version"] is None
    assert config["status"] == "draft"
    assert config["payload"]["agent"]["tone"] == "formal"
    dumped = json.dumps(config["payload"])
    assert "sm://" in json.dumps(
        {
            "channel": channel["secret_reference"],
            "mcp": [row["credentials_reference"] for row in integrations],
        }
    )
    assert "plain-secret" not in dumped
    assert channel["status"] == "disabled"
    assert channel["secret_reference"] == "sm://tenant-b/channel/simulated"
    assert len(integrations) == 1
    assert integrations[0]["kind"] == "mcp"
    assert integrations[0]["server_id"] == "fake-appointments-b"
    assert integrations[0]["status"] == "disabled"
    assert "provision" in set(audits)
    assert int(knowledge_rows or 0) == 0
    resolver = TenantService(service)
    with pytest.raises(TenantResolutionError) as caught:
        await resolver.resolve("simulated", "tenant-b-simulated")
    assert caught.value.code == "disabled_channel_account"


@pytest.mark.anyio
@pytest.mark.integration
async def test_conflicting_channel_mapping_rolls_back_new_tenant(
    tmp_path: Path,
    engine: AsyncEngine,
    service: TenantOnboardingService,
) -> None:
    first_root = _package_for(
        tmp_path / "b",
        slug="tenant-b",
        account="shared-simulated",
        server_id="fake-appointments-b",
    )
    second_root = _package_for(
        tmp_path / "c",
        slug="tenant-c",
        account="shared-simulated",
        server_id="fake-appointments-c",
    )
    await service.provision(_tenant_package(first_root), PLATFORM_PRINCIPAL)
    with pytest.raises(OnboardingError) as conflict:
        await service.provision(_tenant_package(second_root), PLATFORM_PRINCIPAL)
    assert conflict.value.code == "channel_conflict"
    slugs = []
    async with engine.connect() as connection:
        slugs = list(
            (await connection.execute(select(tenant_table.c.slug))).scalars().all()
        )
        mappings = await connection.scalar(
            select(func.count()).select_from(channel_integration_table)
        )
    assert slugs == ["tenant-b"]
    assert int(mappings or 0) == 1


@pytest.mark.anyio
@pytest.mark.integration
async def test_disable_blocks_new_effects_preserves_audit_and_leaves_a_intact(
    tmp_path: Path,
    engine: AsyncEngine,
    service: TenantOnboardingService,
) -> None:
    config_service = ConfigurationService(SqlAlchemyConfigRepository(engine))
    await config_service.publish(
        TENANT_A_ADMIN, TenantConfigDraft(agent=AgentConfig(tone="cordial"))
    )
    now = datetime.now(UTC)
    job_store = SqlAlchemyJobStore(engine)
    await job_store.put(
        ScheduledJob(
            tenant_id=TENANT_A,
            id=uuid4(),
            type=JOB_TYPE,
            payload={"schema_version": 1, "appointment_id": "a-1"},
            business_key="a-1:pre_appointment",
            scheduled_for=now,
            schedule_version=1,
            status="pending",
            attempts=0,
            lock_owner=None,
            lock_expires_at=None,
            last_error=None,
            created_at=now,
            updated_at=now,
        )
    )
    root = _package_for(
        tmp_path / "b",
        slug="tenant-b",
        account="tenant-b-simulated",
        server_id="fake-appointments-b",
    )
    provisioned = await service.provision(_tenant_package(root), PLATFORM_PRINCIPAL)
    async with engine.begin() as connection:
        await connection.execute(
            scheduled_job_table.insert().values(
                tenant_id=provisioned.identity.tenant_id,
                id=uuid4(),
                type=JOB_TYPE,
                payload={"schema_version": 1, "appointment_id": "b-1"},
                business_key="b-1:pre_appointment",
                scheduled_for=now,
                schedule_version=1,
                status="pending",
                attempts=0,
                lock_owner=None,
                lock_expires_at=None,
                last_error=None,
                created_at=now,
                updated_at=now,
            )
        )
    admin_b = TenantAdminContext(
        identity=provisioned.identity,
        principal_id=PLATFORM_PRINCIPAL.principal_id,
        roles=frozenset({"platform_admin"}),
        correlation_id=uuid4(),
    )
    await service.disable(admin_b, "cutover-hold")
    await service.disable(admin_b, "cutover-hold")
    async with engine.connect() as connection:
        tenant_a = (
            (
                await connection.execute(
                    select(tenant_table).where(tenant_table.c.id == TENANT_A)
                )
            )
            .mappings()
            .one()
        )
        tenant_b = (
            (
                await connection.execute(
                    select(tenant_table).where(
                        tenant_table.c.id == provisioned.identity.tenant_id
                    )
                )
            )
            .mappings()
            .one()
        )
        config_a = (
            (
                await connection.execute(
                    select(tenant_config_table.c.payload).where(
                        tenant_config_table.c.tenant_id == TENANT_A
                    )
                )
            )
            .scalars()
            .one()
        )
        jobs = (
            await connection.execute(
                select(scheduled_job_table.c.tenant_id, scheduled_job_table.c.status)
            )
        ).all()
        b_audits = (
            (
                await connection.execute(
                    select(audit_event_table.c.action).where(
                        audit_event_table.c.tenant_id == provisioned.identity.tenant_id
                    )
                )
            )
            .scalars()
            .all()
        )
    assert tenant_a["status"] == "active"
    assert config_a["agent"]["tone"] == "cordial"
    assert tenant_b["status"] == "disabled"
    by_tenant = {row[0]: row[1] for row in jobs}
    assert by_tenant[TENANT_A] == "pending"
    assert by_tenant[provisioned.identity.tenant_id] == "cancelled"
    assert "provision" in set(b_audits)
    assert "disable" in set(b_audits)
    with pytest.raises(OnboardingError) as caught:
        await service.require_active(provisioned.identity)
    assert caught.value.code == "tenant_disabled"
    assert "not available" in caught.value.safe_message.lower()
    await service.require_active(TENANT_A_IDENTITY)
    async with engine.begin() as connection:
        await connection.execute(
            scheduled_job_table.insert().values(
                tenant_id=provisioned.identity.tenant_id,
                id=UUID("00000000-0000-4000-8000-0000000000bb"),
                type=JOB_TYPE,
                payload={"schema_version": 1, "appointment_id": "b-2"},
                business_key="b-2:pre_appointment",
                scheduled_for=now,
                schedule_version=1,
                status="pending",
                attempts=0,
                lock_owner=None,
                lock_expires_at=None,
                last_error=None,
                created_at=now,
                updated_at=now,
            )
        )
    with pytest.raises(DomainError) as blocked_put:
        await job_store.put(
            ScheduledJob(
                tenant_id=provisioned.identity.tenant_id,
                id=uuid4(),
                type=JOB_TYPE,
                payload={"schema_version": 1, "appointment_id": "b-3"},
                business_key="b-3:pre_appointment",
                scheduled_for=now,
                schedule_version=1,
                status="pending",
                attempts=0,
                lock_owner=None,
                lock_expires_at=None,
                last_error=None,
                created_at=now,
                updated_at=now,
            )
        )
    assert blocked_put.value.code == "tenant_disabled"
    claimed = await job_store.claim_due(now=now, owner="worker-1", lock_until=now)
    assert claimed is not None
    assert claimed.tenant_id == TENANT_A
    second = await job_store.claim_due(now=now, owner="worker-1", lock_until=now)
    assert second is None or second.tenant_id == TENANT_A
    disable_payloads = []
    async with engine.connect() as connection:
        disable_payloads = list(
            (
                await connection.execute(
                    select(audit_event_table.c.payload).where(
                        audit_event_table.c.tenant_id == provisioned.identity.tenant_id,
                        audit_event_table.c.action == "disable",
                    )
                )
            )
            .scalars()
            .all()
        )
    assert any(
        isinstance(row, dict) and row.get("reason") == "cutover-hold"
        for row in disable_payloads
    )
    assert all("plain-secret" not in str(row) for row in disable_payloads)


@pytest.mark.anyio
@pytest.mark.integration
async def test_api_provision_creates_disabled_tenant(
    tmp_path: Path,
    engine: AsyncEngine,
    service: TenantOnboardingService,
) -> None:
    root = _package_for(
        tmp_path / "b",
        slug="tenant-b",
        account="tenant-b-simulated",
        server_id="fake-appointments-b",
    )
    app = FastAPI()
    app.include_router(create_onboarding_router())
    app.state.onboarding_service = service
    app.state.tenant_packages_dir = tmp_path
    app.state.admin_authenticator = admin_authenticator({TOKEN: PLATFORM_PRINCIPAL})
    client = TestClient(app, headers=bearer(TOKEN))
    created = client.post(
        "/v1/admin/tenants/provision",
        json={"package_path": str(root)},
    )
    assert created.status_code == 200
    body = created.json()
    assert body["slug"] == "tenant-b"
    assert body["status"] == "disabled"
    listed = client.get("/v1/admin/tenants/tenant-b")
    assert listed.status_code == 200
    disabled = client.post(
        "/v1/admin/tenants/tenant-b/disable",
        json={"reason": "maintenance"},
    )
    assert disabled.status_code == 200


@pytest.mark.anyio
@pytest.mark.integration
async def test_cli_provision_and_disable(
    tmp_path: Path,
    engine: AsyncEngine,
    service: TenantOnboardingService,
) -> None:
    root = _package_for(
        tmp_path / "b",
        slug="tenant-b",
        account="tenant-b-simulated",
        server_id="fake-appointments-b",
    )
    exit_code = await asyncio.to_thread(
        lambda: onboarding_cli(
            [
                "provision",
                str(root),
                "--principal-id",
                str(PLATFORM_PRINCIPAL.principal_id),
                "--role",
                "platform_admin",
            ],
            service=service,
        )
    )
    assert exit_code == 0
    package = load_tenant_package(root)
    assert package.tenant.slug == "tenant-b"
    disable_exit = await asyncio.to_thread(
        lambda: onboarding_cli(
            [
                "disable",
                "tenant-b",
                "--principal-id",
                str(PLATFORM_PRINCIPAL.principal_id),
                "--role",
                "platform_admin",
                "--reason",
                "maintenance",
            ],
            service=service,
        )
    )
    assert disable_exit == 0
