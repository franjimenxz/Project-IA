from __future__ import annotations

import hashlib
import subprocess
import sys
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, func, select, text
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
    AppointmentPolicy,
    TenantAdminContext,
    TenantConfigDraft,
)
from ia_mcp.configuration.service import ConfigurationService
from ia_mcp.conversation.adapters.sqlalchemy import conversation_table, message_table
from ia_mcp.knowledge.adapters.object_store import InMemoryObjectStore
from ia_mcp.knowledge.adapters.sqlalchemy import SqlAlchemyKnowledgeRepository
from ia_mcp.knowledge.models import DocumentSource, KnowledgeQuery
from ia_mcp.knowledge.service import KnowledgeService
from ia_mcp.mcp.registry import available
from ia_mcp.observability.run_query import RunNotFound
from ia_mcp.onboarding.commands import OnboardingError, Principal, load_tenant_package
from ia_mcp.onboarding.preflight import default_preflight_checks
from ia_mcp.onboarding.service import (
    TenantOnboardingService,
    integration_table,
    tenant_context_for,
)
from ia_mcp.onboarding.validator import validate_package
from ia_mcp.scheduling.models import JOB_TYPE, ScheduledJob
from ia_mcp.scheduling.service import SqlAlchemyJobStore, scheduled_job_table
from ia_mcp.shared.errors import DomainError
from ia_mcp.tenancy.models import TenantContext, TenantIdentity
from tests.unit.knowledge.fakes import FakeChunker, FakeEmbedding, FakeParser
from tests.unit.onboarding.helpers import write_package

ROOT = Path(__file__).resolve().parents[2]
FIXTURE_B = ROOT / "tenants" / "fixtures" / "tenant-b"
CANARY_B_FILE = FIXTURE_B / "knowledge" / "hours-b.txt"
CANARY_A = b"canary-tenant-a clinic hours eight to sixteen"
REGISTERED_BASE = "9bbb790"
DATABASE_URL = "postgresql+psycopg://francojimenez@127.0.0.1:5432/ia_mcp_p02_t03"

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
A_TOOLS = frozenset(
    {
        "appointments.search",
        "appointments.get",
        "appointments.create",
        "appointments.cancel",
        "appointments.reschedule",
        "appointments.confirm",
    }
)
B_TOOLS = frozenset(
    {
        "appointments.search",
        "appointments.get",
        "appointments.create",
    }
)


class _SmReferenceSecrets:
    async def resolvable(self, tenant: TenantContext, reference: str) -> bool:
        return reference.startswith("sm://")


class _ConfiguredMcpHealth:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def healthy(self, tenant: TenantContext) -> bool:
        async with self._engine.connect() as connection:
            server_id = await connection.scalar(
                text("SELECT server_id FROM integration WHERE tenant_id = :tenant_id"),
                {"tenant_id": tenant.tenant_id},
            )
        return bool(server_id)


class _SyntheticEvalSmoke:
    async def passed(self, tenant: TenantContext) -> bool:
        return True


class _MissingRunQuery:
    async def get(
        self,
        tenant: TenantContext,
        run_id: UUID,
        *,
        tools_cursor: str | None = None,
        tools_limit: int = 50,
        events_cursor: str | None = None,
        events_limit: int = 50,
    ) -> None:
        raise RunNotFound()


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


def _onboarding_service(engine: AsyncEngine) -> TenantOnboardingService:
    return TenantOnboardingService(
        engine,
        checks=default_preflight_checks(
            engine,
            investigation_query=_MissingRunQuery(),
            secrets=_SmReferenceSecrets(),
            mcp_health=_ConfiguredMcpHealth(engine),
            eval_smoke=_SyntheticEvalSmoke(),
        ),
    )


def _knowledge(engine: AsyncEngine) -> KnowledgeService:
    return KnowledgeService(
        repository=SqlAlchemyKnowledgeRepository(engine),
        parser=FakeParser(),
        chunker=FakeChunker(),
        embeddings=FakeEmbedding(),
        object_store=InMemoryObjectStore(),
    )


async def _seed_tenant_a(engine: AsyncEngine, now: datetime) -> None:
    config_service = ConfigurationService(SqlAlchemyConfigRepository(engine))
    published = await config_service.publish(
        TENANT_A_ADMIN,
        TenantConfigDraft(
            agent=AgentConfig(tone="cordial"),
            enabled_skills=frozenset({"faq", "appointments"}),
            appointments=AppointmentPolicy(
                required_fields=("specialty", "date_from"),
            ),
        ),
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
            integration_table.insert().values(
                id=uuid4(),
                tenant_id=TENANT_A,
                kind="mcp",
                server_id="fake-appointments-a",
                credentials_reference="sm://tenant-a/mcp/appointments",
                capabilities=sorted(A_TOOLS),
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
                mcp_server_id="fake-appointments-a",
                status="succeeded",
                usage=None,
                started_at=now,
                finished_at=now,
                error_code=None,
            )
        )
    knowledge = _knowledge(engine)
    ctx_a = TenantContext(
        tenant_id=TENANT_A,
        tenant_slug="tenant-a",
        config_version=1,
        correlation_id=uuid4(),
    )
    draft = await knowledge.ingest(
        ctx_a,
        DocumentSource(
            filename="hours-a.txt",
            payload=CANARY_A,
            mime_type="text/plain",
        ),
    )
    await knowledge.publish(ctx_a, draft.document_id, draft.version)
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


async def _ingest_package_canary(
    engine: AsyncEngine, tenant: TenantContext
) -> bytes:
    payload = CANARY_B_FILE.read_bytes()
    knowledge = _knowledge(engine)
    draft = await knowledge.ingest(
        tenant,
        DocumentSource(
            filename=CANARY_B_FILE.name,
            payload=payload,
            mime_type="text/plain",
        ),
    )
    await knowledge.publish(tenant, draft.document_id, draft.version)
    return payload


@pytest.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    _reset_schema()
    db = create_async_engine(DATABASE_URL)
    try:
        yield db
    finally:
        await db.dispose()


def test_tenant_b_package_includes_distinct_canary_corpus() -> None:
    assert CANARY_B_FILE.is_file()
    payload = CANARY_B_FILE.read_bytes()
    assert b"canary-tenant-b" in payload
    assert b"canary-tenant-a" not in payload
    digest = hashlib.sha256(payload).hexdigest()
    report = validate_package(FIXTURE_B)
    assert report.valid is True
    package = load_tenant_package(FIXTURE_B)
    assert package.tenant.slug == "tenant-b"
    assert package.config.mcp.server_id == "fake-appointments-b"
    assert package.config.appointments.required_fields == (
        "specialty",
        "practitioner",
        "date_from",
        "date_to",
    )
    assert package.config.enabled_tools == (
        "appointments.search",
        "appointments.get",
        "appointments.create",
    )
    checksums = {item.checksum for item in package.knowledge.documents}
    assert digest in checksums
    assert package.integrations.channels[0].secret_reference.startswith("sm://")
    assert package.integrations.integrations[0].credentials_reference.startswith(
        "sm://"
    )
    dumped = report.model_dump_json()
    assert "plain-secret" not in dumped
    assert "sk-live" not in dumped


def test_invalid_package_fails_before_persist(tmp_path: Path) -> None:
    package = write_package(tmp_path, integrations={"token": "plain-secret"})
    report = validate_package(package)
    assert report.valid is False
    assert "secret values are forbidden" in report.errors[0].message
    assert "plain-secret" not in report.model_dump_json()
    with pytest.raises(OnboardingError) as denied:
        load_tenant_package(package)
    assert denied.value.code == "invalid_package"


def test_inconsistent_config_fails_validation(tmp_path: Path) -> None:
    package = write_package(
        tmp_path,
        config={"knowledge": {"namespace": "other-tenant"}},
    )
    report = validate_package(package)
    assert report.valid is False
    assert any("namespace" in issue.message for issue in report.errors)


def test_secret_reference_is_validated_without_printing_value() -> None:
    report = validate_package(FIXTURE_B)
    package = load_tenant_package(FIXTURE_B)
    dumped = report.model_dump_json()
    assert report.valid is True
    assert package.integrations.channels[0].secret_reference == (
        "sm://tenant-b/channel/simulated"
    )
    assert package.integrations.integrations[0].credentials_reference == (
        "sm://tenant-b/mcp/appointments"
    )
    assert "plain-secret" not in dumped
    assert "Bearer" not in dumped
    assert "sk-live" not in dumped


def test_core_diff_fails_slug_branches_and_passes_this_changeset() -> None:
    from scripts.check_tenant_specific_core import review_changeset

    findings = review_changeset(
        {
            "src/ia_mcp/skills/faq.py": (
                'if tenant.tenant_slug == "tenant-b":\n    return True\n'
            )
        }
    )
    assert findings
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/check_tenant_specific_core.py",
            "--base",
            REGISTERED_BASE,
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "sm://" not in completed.stdout
    assert "plain-secret" not in completed.stdout


@pytest.mark.anyio
@pytest.mark.e2e
async def test_second_tenant_validate_provision_preflight_activate_isolates(
    engine: AsyncEngine,
) -> None:
    now = datetime.now(UTC)
    await _seed_tenant_a(engine, now)
    service = _onboarding_service(engine)
    report = validate_package(FIXTURE_B)
    assert report.valid is True
    assert report.content_hash is not None
    package = load_tenant_package(FIXTURE_B)
    first = await service.provision(package, PLATFORM)
    replayed = await service.provision(package, PLATFORM)
    assert first.identity.tenant_id == replayed.identity.tenant_id
    assert first.status == "disabled"
    ctx_b = tenant_context_for(first)
    payload = await _ingest_package_canary(engine, ctx_b)
    assert b"canary-tenant-b" in payload
    preflight = await service.preflight(ctx_b, content_hash=report.content_hash)
    assert preflight.passed is True
    admin_b = TenantAdminContext(
        identity=first.identity,
        principal_id=PLATFORM.principal_id,
        roles=PLATFORM.roles,
        correlation_id=uuid4(),
    )
    await service.activate(admin_b, preflight.report_hash)
    knowledge = _knowledge(engine)
    hits_b = await knowledge.search(
        ctx_b, KnowledgeQuery(text="canary-tenant-b night hours", limit=5)
    )
    ctx_a = TenantContext(
        tenant_id=TENANT_A,
        tenant_slug="tenant-a",
        config_version=1,
        correlation_id=uuid4(),
    )
    hits_a = await knowledge.search(
        ctx_a, KnowledgeQuery(text="canary-tenant-a clinic hours", limit=5)
    )
    assert any("canary-tenant-b" in hit.text for hit in hits_b)
    assert all("canary-tenant-a" not in hit.text for hit in hits_b)
    assert any("canary-tenant-a" in hit.text for hit in hits_a)
    assert all("canary-tenant-b" not in hit.text for hit in hits_a)
    async with engine.connect() as connection:
        integration_a = (
            (
                await connection.execute(
                    select(
                        integration_table.c.server_id,
                        integration_table.c.capabilities,
                    ).where(integration_table.c.tenant_id == TENANT_A)
                )
            )
            .mappings()
            .one()
        )
        integration_b = (
            (
                await connection.execute(
                    select(
                        integration_table.c.server_id,
                        integration_table.c.capabilities,
                    ).where(integration_table.c.tenant_id == first.identity.tenant_id)
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
            .mappings()
            .one()
        )
        config_b = (
            (
                await connection.execute(
                    select(tenant_config_table.c.payload).where(
                        tenant_config_table.c.tenant_id == first.identity.tenant_id
                    )
                )
            )
            .mappings()
            .one()
        )
        tenant_a = (
            (
                await connection.execute(
                    select(tenant_table).where(tenant_table.c.id == TENANT_A)
                )
            )
            .mappings()
            .one()
        )
        mapping_count = await connection.scalar(
            select(func.count())
            .select_from(channel_integration_table)
            .where(channel_integration_table.c.tenant_id == first.identity.tenant_id)
        )
        job_a = await connection.scalar(
            select(scheduled_job_table.c.status).where(
                scheduled_job_table.c.tenant_id == TENANT_A
            )
        )
        run_a = (
            (
                await connection.execute(
                    select(
                        agent_run_table.c.status,
                        agent_run_table.c.mcp_server_id,
                        agent_run_table.c.config_version,
                    ).where(agent_run_table.c.tenant_id == TENANT_A)
                )
            )
            .mappings()
            .one()
        )
        status_b = await connection.scalar(
            select(tenant_table.c.status).where(
                tenant_table.c.id == first.identity.tenant_id
            )
        )
    assert integration_a["server_id"] == "fake-appointments-a"
    assert integration_b["server_id"] == "fake-appointments-b"
    assert integration_a["server_id"] != integration_b["server_id"]
    tools_a = available(A_TOOLS, A_TOOLS, A_TOOLS)
    tools_b = available(
        frozenset(integration_b["capabilities"]),
        frozenset(package.config.enabled_tools),
        frozenset(package.config.enabled_tools),
    )
    assert tools_a == A_TOOLS
    assert tools_b == B_TOOLS
    assert tools_a != tools_b
    assert config_a["payload"]["agent"]["tone"] == "cordial"
    assert config_a["payload"]["appointments"]["required_fields"] == [
        "specialty",
        "date_from",
    ]
    assert config_b["payload"]["agent"]["tone"] == "formal"
    assert config_b["payload"]["appointments"]["required_fields"] == [
        "specialty",
        "practitioner",
        "date_from",
        "date_to",
    ]
    assert tenant_a["status"] == "active"
    assert tenant_a["active_config_version"] == 1
    assert mapping_count == 1
    assert job_a == "pending"
    assert run_a["status"] == "succeeded"
    assert run_a["mcp_server_id"] == "fake-appointments-a"
    assert run_a["config_version"] == 1
    assert status_b == "active"
    await service.disable(admin_b, "cutover-hold")
    job_store = SqlAlchemyJobStore(engine)
    with pytest.raises(DomainError) as blocked:
        await job_store.put(
            ScheduledJob(
                tenant_id=first.identity.tenant_id,
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
        status_a = await connection.scalar(
            select(tenant_table.c.status).where(tenant_table.c.id == TENANT_A)
        )
        disabled_b = await connection.scalar(
            select(tenant_table.c.status).where(
                tenant_table.c.id == first.identity.tenant_id
            )
        )
        job_after = await connection.scalar(
            select(scheduled_job_table.c.status).where(
                scheduled_job_table.c.tenant_id == TENANT_A
            )
        )
        run_after = await connection.scalar(
            select(agent_run_table.c.status).where(
                agent_run_table.c.tenant_id == TENANT_A
            )
        )
    assert status_a == "active"
    assert disabled_b == "disabled"
    assert job_after == "claimed"
    assert run_after == "succeeded"
    with pytest.raises(OnboardingError) as inactive:
        await service.require_active(first.identity)
    assert inactive.value.code == "tenant_disabled"
    await service.require_active(TENANT_A_IDENTITY)


@pytest.mark.anyio
@pytest.mark.e2e
async def test_stale_preflight_hash_cannot_activate(engine: AsyncEngine) -> None:
    now = datetime.now(UTC)
    await _seed_tenant_a(engine, now)
    service = _onboarding_service(engine)
    report = validate_package(FIXTURE_B)
    assert report.content_hash is not None
    provisioned = await service.provision(load_tenant_package(FIXTURE_B), PLATFORM)
    await _ingest_package_canary(engine, tenant_context_for(provisioned))
    preflight = await service.preflight(
        tenant_context_for(provisioned), content_hash=report.content_hash
    )
    assert preflight.passed is True
    admin = TenantAdminContext(
        identity=provisioned.identity,
        principal_id=PLATFORM.principal_id,
        roles=PLATFORM.roles,
        correlation_id=uuid4(),
    )
    with pytest.raises(OnboardingError) as denied:
        await service.activate(admin, "0" * 64)
    assert denied.value.code == "stale_preflight"
    async with engine.connect() as connection:
        status_b = await connection.scalar(
            select(tenant_table.c.status).where(
                tenant_table.c.id == provisioned.identity.tenant_id
            )
        )
        status_a = await connection.scalar(
            select(tenant_table.c.status).where(tenant_table.c.id == TENANT_A)
        )
    assert status_b == "disabled"
    assert status_a == "active"
