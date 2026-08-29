from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from alembic import command
from ia_mcp.agent_runtime.run_repository import agent_run_table
from ia_mcp.configuration.adapters.sqlalchemy import (
    SqlAlchemyConfigRepository,
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
from ia_mcp.conversation.adapters.sqlalchemy import conversation_table, message_table
from ia_mcp.onboarding.commands import OnboardingError, Principal, load_tenant_package
from ia_mcp.onboarding.preflight import PREFLIGHT_CHECK_NAMES, CheckOutcome
from ia_mcp.onboarding.service import TenantOnboardingService, tenant_context_for
from ia_mcp.onboarding.validator import validate_package
from ia_mcp.scheduling.models import JOB_TYPE, ScheduledJob
from ia_mcp.scheduling.service import SqlAlchemyJobStore, scheduled_job_table
from ia_mcp.shared.errors import DomainError
from ia_mcp.tenancy.models import TenantContext, TenantIdentity
from tests.fixtures.database import DATABASE_URL
from tests.unit.onboarding.helpers import write_package

ROOT = Path(__file__).resolve().parents[2]

PLATFORM = Principal(
    principal_id=UUID("11111111-1111-1111-1111-111111111111"),
    roles=frozenset({"platform_admin"}),
)
TENANT_A = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
TENANT_A_IDENTITY = TenantIdentity(tenant_id=TENANT_A, tenant_slug="tenant-a")
TENANT_A_ADMIN = TenantAdminContext(
    identity=TENANT_A_IDENTITY,
    principal_id=UUID("22222222-2222-2222-2222-222222222222"),
    roles=frozenset({"tenant_admin"}),
    correlation_id=UUID("33333333-3333-3333-3333-333333333333"),
)
CHANNEL_A = UUID("aa111111-1111-1111-1111-111111111111")
CONVERSATION_A = UUID("aa222222-2222-2222-2222-222222222222")
MESSAGE_A = UUID("aa333333-3333-3333-3333-333333333333")
RUN_A = UUID("aa444444-4444-4444-4444-444444444444")


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


def _package_root(root: Path) -> Path:
    return write_package(
        root,
        tenant={"slug": "tenant-b", "display_name": "tenant-b synthetic"},
        config={
            "knowledge": {"namespace": "tenant-b"},
            "mcp": {"server_id": "fake-tenant-b"},
        },
        integrations={
            "channels": [
                {
                    "channel": "simulated",
                    "external_account_id": "tenant-b-simulated",
                    "secret_reference": "sm://tenant-b/channel/simulated",
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


def _passing_checks() -> tuple[StubCheck, ...]:
    return tuple(StubCheck(name=name) for name in PREFLIGHT_CHECK_NAMES)


async def _seed_tenant_a(engine: AsyncEngine, now: datetime) -> None:
    config_service = ConfigurationService(SqlAlchemyConfigRepository(engine))
    published = await config_service.publish(
        TENANT_A_ADMIN, TenantConfigDraft(agent=AgentConfig(tone="cordial"))
    )
    await config_service.activate(TENANT_A_ADMIN, int(published.version))
    async with engine.begin() as connection:
        await connection.execute(
            channel_integration_table.insert().values(
                id=CHANNEL_A,
                tenant_id=TENANT_A,
                channel="simulated",
                external_account_id="acct-a",
                secret_reference="sm://tenant-a/channel/simulated",
                status="active",
            )
        )
        await connection.execute(
            conversation_table.insert().values(
                id=CONVERSATION_A,
                tenant_id=TENANT_A,
                channel_integration_id=CHANNEL_A,
                external_user_ref="user-a",
                status="bot_owned",
                last_message_at=now,
                lock_version=1,
            )
        )
        await connection.execute(
            message_table.insert().values(
                id=MESSAGE_A,
                tenant_id=TENANT_A,
                conversation_id=CONVERSATION_A,
                channel_integration_id=CHANNEL_A,
                direction="inbound",
                external_message_id="m-a",
                content="hours",
                content_type="text",
                occurred_at=now,
                received_at=now,
                dedupe_hash="a" * 64,
            )
        )
        await connection.execute(
            agent_run_table.insert().values(
                id=RUN_A,
                tenant_id=TENANT_A,
                conversation_id=CONVERSATION_A,
                config_version=1,
                correlation_id=UUID("55555555-5555-5555-5555-555555555555"),
                input_message_id=MESSAGE_A,
                model_provider="fake",
                model_name="fake",
                skill="faq",
                workflow_type=None,
                mcp_server_id=None,
                status="succeeded",
                usage=None,
                started_at=now,
                finished_at=now,
                error_code=None,
            )
        )
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


@pytest.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    _reset_schema()
    db = create_async_engine(DATABASE_URL)
    try:
        yield db
    finally:
        await db.dispose()


@pytest.mark.anyio
@pytest.mark.e2e
async def test_activate_b_does_not_change_runs_jobs_config_of_a(
    tmp_path: Path, engine: AsyncEngine
) -> None:
    now = datetime.now(UTC)
    await _seed_tenant_a(engine, now)
    service = TenantOnboardingService(engine, checks=_passing_checks())
    root = _package_root(tmp_path / "b")
    h1 = validate_package(root).content_hash
    assert h1 is not None
    provisioned = await service.provision(load_tenant_package(root), PLATFORM)
    report = await service.preflight(tenant_context_for(provisioned), content_hash=h1)
    admin_b = TenantAdminContext(
        identity=provisioned.identity,
        principal_id=PLATFORM.principal_id,
        roles=PLATFORM.roles,
        correlation_id=uuid4(),
    )
    await service.activate(admin_b, report.report_hash)
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
        config_a = (
            (
                await connection.execute(
                    select(
                        tenant_config_table.c.payload,
                        tenant_config_table.c.version,
                        tenant_config_table.c.status,
                    ).where(tenant_config_table.c.tenant_id == TENANT_A)
                )
            )
            .mappings()
            .one()
        )
        job_a = (
            (
                await connection.execute(
                    select(scheduled_job_table.c.status).where(
                        scheduled_job_table.c.tenant_id == TENANT_A
                    )
                )
            )
            .scalars()
            .one()
        )
        run_a = (
            (
                await connection.execute(
                    select(
                        agent_run_table.c.status,
                        agent_run_table.c.skill,
                        agent_run_table.c.config_version,
                    ).where(agent_run_table.c.tenant_id == TENANT_A)
                )
            )
            .mappings()
            .one()
        )
        tenant_b = (
            (
                await connection.execute(
                    select(tenant_table.c.status).where(
                        tenant_table.c.id == provisioned.identity.tenant_id
                    )
                )
            )
            .scalars()
            .one()
        )
    assert tenant_a["status"] == "active"
    assert tenant_a["active_config_version"] == 1
    assert config_a["payload"]["agent"]["tone"] == "cordial"
    assert config_a["version"] == 1
    assert job_a == "pending"
    assert run_a["status"] == "succeeded"
    assert run_a["skill"] == "faq"
    assert run_a["config_version"] == 1
    assert tenant_b == "active"


@pytest.mark.anyio
@pytest.mark.e2e
async def test_disable_after_activate_blocks_new_effects_and_leaves_a_intact(
    tmp_path: Path, engine: AsyncEngine
) -> None:
    now = datetime.now(UTC)
    await _seed_tenant_a(engine, now)
    service = TenantOnboardingService(engine, checks=_passing_checks())
    root = _package_root(tmp_path / "b")
    h1 = validate_package(root).content_hash
    assert h1 is not None
    provisioned = await service.provision(load_tenant_package(root), PLATFORM)
    report = await service.preflight(tenant_context_for(provisioned), content_hash=h1)
    admin_b = TenantAdminContext(
        identity=provisioned.identity,
        principal_id=PLATFORM.principal_id,
        roles=PLATFORM.roles,
        correlation_id=uuid4(),
    )
    await service.activate(admin_b, report.report_hash)
    await service.disable(admin_b, "cutover-hold")
    job_store = SqlAlchemyJobStore(engine)
    with pytest.raises(DomainError) as blocked:
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
    assert blocked.value.code == "tenant_disabled"
    claimed = await job_store.claim_due(now=now, owner="worker-1", lock_until=now)
    assert claimed is not None
    assert claimed.tenant_id == TENANT_A
    async with engine.connect() as connection:
        job_a = await connection.scalar(
            select(scheduled_job_table.c.status).where(
                scheduled_job_table.c.tenant_id == TENANT_A
            )
        )
        run_a = await connection.scalar(
            select(agent_run_table.c.status).where(agent_run_table.c.tenant_id == TENANT_A)
        )
        status_a = await connection.scalar(
            select(tenant_table.c.status).where(tenant_table.c.id == TENANT_A)
        )
        status_b = await connection.scalar(
            select(tenant_table.c.status).where(
                tenant_table.c.id == provisioned.identity.tenant_id
            )
        )
    assert job_a == "claimed"
    assert run_a == "succeeded"
    assert status_a == "active"
    assert status_b == "disabled"
    with pytest.raises(OnboardingError) as inactive:
        await service.require_active(provisioned.identity)
    assert inactive.value.code == "tenant_disabled"
    await service.require_active(TENANT_A_IDENTITY)
