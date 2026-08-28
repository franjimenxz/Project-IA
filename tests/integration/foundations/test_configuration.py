from __future__ import annotations

import asyncio
import inspect
import json
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic.config import Config
from pydantic import ValidationError
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import command
from ia_mcp.configuration.adapters.sqlalchemy import (
    SqlAlchemyConfigRepository,
    audit_event_table,
    tenant_config_table,
)
from ia_mcp.configuration.models import (
    AgentConfig,
    McpConfig,
    TenantAdminContext,
    TenantConfigDraft,
)
from ia_mcp.configuration.ports import ConfigurationError
from ia_mcp.configuration.service import ConfigurationService
from ia_mcp.tenancy.models import TenantContext, TenantIdentity

ROOT = Path(__file__).resolve().parents[3]
DATABASE_URL = "postgresql+psycopg://francojimenez@127.0.0.1:5432/ia_mcp_p02_t03"

TENANT_A = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
TENANT_B = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
TENANT_A_IDENTITY = TenantIdentity(tenant_id=TENANT_A, tenant_slug="tenant-a")
TENANT_B_IDENTITY = TenantIdentity(tenant_id=TENANT_B, tenant_slug="tenant-b")
TENANT_A_ADMIN_CTX = TenantAdminContext(
    identity=TENANT_A_IDENTITY,
    principal_id=UUID("11111111-1111-1111-1111-111111111111"),
    roles=frozenset({"tenant_admin"}),
    correlation_id=uuid4(),
)
TENANT_B_ADMIN_CTX = TenantAdminContext(
    identity=TENANT_B_IDENTITY,
    principal_id=UUID("22222222-2222-2222-2222-222222222222"),
    roles=frozenset({"tenant_admin"}),
    correlation_id=uuid4(),
)


def draft(*, tone: str, credentials_reference: str | None = None) -> TenantConfigDraft:
    mcp = (
        McpConfig(credentials_reference=credentials_reference)
        if credentials_reference is not None
        else McpConfig()
    )
    return TenantConfigDraft(agent=AgentConfig(tone=tone), mcp=mcp)


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


@pytest.fixture
async def config_service() -> AsyncIterator[ConfigurationService]:
    _reset_schema()
    engine = create_async_engine(DATABASE_URL)
    service = ConfigurationService(SqlAlchemyConfigRepository(engine))
    try:
        yield service
    finally:
        await engine.dispose()


@pytest.mark.anyio
@pytest.mark.integration
async def test_publishing_change_creates_new_immutable_version(
    config_service: ConfigurationService,
) -> None:
    v1 = await config_service.publish(TENANT_A_ADMIN_CTX, draft(tone="cordial"))
    v2 = await config_service.publish(TENANT_A_ADMIN_CTX, draft(tone="formal"))
    assert (v1.version, v2.version) == (1, 2)
    assert v1.agent.tone == "cordial"


@pytest.mark.anyio
@pytest.mark.integration
async def test_published_payload_and_hash_stay_on_v1(
    config_service: ConfigurationService,
) -> None:
    v1 = await config_service.publish(TENANT_A_ADMIN_CTX, draft(tone="cordial"))
    await config_service.publish(TENANT_A_ADMIN_CTX, draft(tone="formal"))
    engine = create_async_engine(DATABASE_URL)
    try:
        async with engine.connect() as connection:
            rows = (
                await connection.execute(
                    select(
                        tenant_config_table.c.version,
                        tenant_config_table.c.content_hash,
                        tenant_config_table.c.payload,
                    ).where(tenant_config_table.c.tenant_id == TENANT_A)
                )
            ).mappings().all()
            by_version = {int(row["version"]): row for row in rows}
            assert by_version[1]["payload"]["agent"]["tone"] == "cordial"
            assert by_version[2]["payload"]["agent"]["tone"] == "formal"
            assert by_version[1]["content_hash"] != by_version[2]["content_hash"]
            with pytest.raises(DBAPIError):
                await connection.execute(
                    text("UPDATE tenant_config SET payload = '{}'::jsonb")
                )
    finally:
        await engine.dispose()
    assert v1.agent.tone == "cordial"


@pytest.mark.anyio
@pytest.mark.integration
async def test_capture_pins_active_version_across_later_activation(
    config_service: ConfigurationService,
) -> None:
    engine = create_async_engine(DATABASE_URL)
    repository = SqlAlchemyConfigRepository(engine)
    try:
        await config_service.publish(TENANT_A_ADMIN_CTX, draft(tone="cordial"))
        await config_service.activate(TENANT_A_ADMIN_CTX, 1)
        correlation_id = UUID("33333333-3333-3333-3333-333333333333")
        context, config = await config_service.capture(TENANT_A_IDENTITY, correlation_id)
        assert context.config_version == 1
        assert context.correlation_id == correlation_id
        assert config.agent.tone == "cordial"
        await config_service.publish(TENANT_A_ADMIN_CTX, draft(tone="formal"))
        await config_service.activate(TENANT_A_ADMIN_CTX, 2)
        pinned = await repository.get_for_runtime(context)
        assert pinned is not None
        assert pinned.version == 1
        assert pinned.agent.tone == "cordial"
    finally:
        await engine.dispose()


@pytest.mark.anyio
@pytest.mark.integration
async def test_rollback_activates_previous_version_and_is_audited(
    config_service: ConfigurationService,
) -> None:
    await config_service.publish(TENANT_A_ADMIN_CTX, draft(tone="cordial"))
    await config_service.publish(TENANT_A_ADMIN_CTX, draft(tone="formal"))
    await config_service.activate(TENANT_A_ADMIN_CTX, 2)
    await config_service.activate(TENANT_A_ADMIN_CTX, 1)
    context, config = await config_service.capture(TENANT_A_IDENTITY, uuid4())
    assert context.config_version == 1
    assert config.agent.tone == "cordial"
    engine = create_async_engine(DATABASE_URL)
    try:
        async with engine.connect() as connection:
            actions = (
                await connection.execute(
                    select(audit_event_table.c.action, audit_event_table.c.version).where(
                        audit_event_table.c.tenant_id == TENANT_A
                    )
                )
            ).all()
            assert ("activate", 1) in {(row[0], row[1]) for row in actions}
    finally:
        await engine.dispose()


@pytest.mark.anyio
@pytest.mark.integration
async def test_concurrent_publish_allocates_distinct_versions(
    config_service: ConfigurationService,
) -> None:
    first, second = await asyncio.gather(
        config_service.publish(TENANT_A_ADMIN_CTX, draft(tone="cordial")),
        config_service.publish(TENANT_A_ADMIN_CTX, draft(tone="formal")),
    )
    assert sorted((first.version, second.version)) == [1, 2]


@pytest.mark.anyio
@pytest.mark.integration
async def test_repository_rejects_cross_tenant_access(
    config_service: ConfigurationService,
) -> None:
    await config_service.publish(TENANT_A_ADMIN_CTX, draft(tone="cordial"))
    await config_service.publish(TENANT_B_ADMIN_CTX, draft(tone="formal"))
    await config_service.activate(TENANT_B_ADMIN_CTX, 1)
    engine = create_async_engine(DATABASE_URL)
    repository = SqlAlchemyConfigRepository(engine)
    try:
        assert await repository.get_version(TENANT_A_IDENTITY, 1) is not None
        assert await repository.get_active(TENANT_A_IDENTITY) is None
        assert await repository.get_for_runtime(
            TenantContext(
                tenant_id=TENANT_A,
                tenant_slug="tenant-a",
                config_version=1,
                correlation_id=uuid4(),
            )
        ) is not None
        mixed = TenantContext(
            tenant_id=TENANT_B,
            tenant_slug="tenant-a",
            config_version=1,
            correlation_id=uuid4(),
        )
        with pytest.raises(ConfigurationError) as exc_info:
            await repository.get_for_runtime(mixed)
        assert exc_info.value.code == "tenant_isolation_violation"
        assert "formal" not in exc_info.value.safe_message
    finally:
        await engine.dispose()


@pytest.mark.integration
def test_draft_serializes_credential_references_only() -> None:
    config = draft(tone="cordial", credentials_reference="secret://mcp/tenant-a")
    serialized = json.dumps(config.model_dump(mode="json"))
    assert "secret://mcp/tenant-a" in serialized
    assert "sk-live" not in serialized
    assert "password" not in serialized
    with pytest.raises(ValidationError):
        TenantConfigDraft.model_validate(
            {
                "agent": {"tone": "cordial"},
                "mcp": {
                    "credentials_reference": "secret://mcp/tenant-a",
                    "api_key": "sk-live",
                },
            }
        )


@pytest.mark.integration
def test_repository_api_does_not_accept_raw_uuid() -> None:
    for name in ("publish", "activate", "get_active", "get_version", "get_for_runtime"):
        parameters = list(
            inspect.signature(getattr(SqlAlchemyConfigRepository, name)).parameters.values()
        )
        first_argument = parameters[1]
        assert first_argument.annotation is not UUID
        assert first_argument.annotation in {TenantAdminContext, TenantIdentity, TenantContext}


@pytest.mark.integration
def test_foundations_migration_up_and_down() -> None:
    _reset_schema()
    alembic_cfg = Config(str(ROOT / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(ROOT / "alembic"))
    alembic_cfg.set_main_option("sqlalchemy.url", DATABASE_URL)
    command.downgrade(alembic_cfg, "base")
    command.upgrade(alembic_cfg, "head")
    command.downgrade(alembic_cfg, "base")
    engine = create_engine(DATABASE_URL)
    with engine.connect() as connection:
        tables = connection.execute(
            text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
        ).scalars().all()
        assert "tenant_config" not in tables
    engine.dispose()
    command.upgrade(alembic_cfg, "head")
