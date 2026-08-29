from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import command
from ia_mcp.agent_runtime.run_repository import (
    SqlAlchemyAgentRunRepository,
    agent_run_table,
)
from ia_mcp.configuration.adapters.sqlalchemy import (
    audit_event_table,
    channel_integration_table,
    tenant_table,
)
from ia_mcp.conversation.adapters.sqlalchemy import (
    SqlAlchemyConversationRepository,
    message_table,
)
from ia_mcp.conversation.models import InboundMessage
from ia_mcp.conversation.ports import ConversationError
from ia_mcp.tenancy.models import TenantContext
from tests.fixtures.database import DATABASE_URL

ROOT = Path(__file__).resolve().parents[3]

TENANT_A = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
TENANT_B = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
CHANNEL_A = UUID("aa111111-1111-1111-1111-111111111111")
CHANNEL_B = UUID("bb111111-1111-1111-1111-111111111111")
CORR_A = UUID("33333333-3333-3333-3333-333333333333")
CORR_B = UUID("44444444-4444-4444-4444-444444444444")
OCCURRED_AT = datetime(2026, 8, 28, 4, 20, tzinfo=UTC)

TENANT_A_CTX = TenantContext(
    tenant_id=TENANT_A,
    tenant_slug="tenant-a",
    config_version=1,
    correlation_id=CORR_A,
)
TENANT_B_CTX = TenantContext(
    tenant_id=TENANT_B,
    tenant_slug="tenant-b",
    config_version=2,
    correlation_id=CORR_B,
)


def inbound(
    *,
    tenant: TenantContext = TENANT_A_CTX,
    channel_integration_id: UUID = CHANNEL_A,
    channel_account_id: str = "acct-a",
    external_message_id: str = "ext-msg-1",
    external_user_id: str = "user-a",
    text: str = "hola",
) -> InboundMessage:
    return InboundMessage(
        channel="simulated",
        channel_account_id=channel_account_id,
        channel_integration_id=channel_integration_id,
        external_message_id=external_message_id,
        external_user_id=external_user_id,
        text=text,
        occurred_at=OCCURRED_AT,
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


def _seed_tenants_and_channels() -> None:
    engine = create_engine(DATABASE_URL)
    now = datetime.now(UTC)
    with engine.begin() as connection:
        connection.execute(
            tenant_table.insert(),
            [
                {
                    "id": TENANT_A,
                    "slug": "tenant-a",
                    "status": "active",
                    "active_config_version": None,
                    "created_at": now,
                    "updated_at": now,
                },
                {
                    "id": TENANT_B,
                    "slug": "tenant-b",
                    "status": "active",
                    "active_config_version": None,
                    "created_at": now,
                    "updated_at": now,
                },
            ],
        )
        connection.execute(
            channel_integration_table.insert(),
            [
                {
                    "id": CHANNEL_A,
                    "tenant_id": TENANT_A,
                    "channel": "simulated",
                    "external_account_id": "acct-a",
                    "secret_reference": "secret://simulated/a",
                    "status": "active",
                },
                {
                    "id": CHANNEL_B,
                    "tenant_id": TENANT_B,
                    "channel": "simulated",
                    "external_account_id": "acct-b",
                    "secret_reference": "secret://simulated/b",
                    "status": "active",
                },
            ],
        )
    engine.dispose()


@pytest.fixture
async def repos() -> AsyncIterator[
    tuple[SqlAlchemyConversationRepository, SqlAlchemyAgentRunRepository]
]:
    _reset_schema()
    _seed_tenants_and_channels()
    engine = create_async_engine(DATABASE_URL)
    conversations = SqlAlchemyConversationRepository(engine)
    runs = SqlAlchemyAgentRunRepository(engine)
    try:
        yield conversations, runs
    finally:
        await engine.dispose()


@pytest.mark.anyio
@pytest.mark.integration
async def test_duplicate_external_message_returns_same_message_and_one_run(
    repos: tuple[SqlAlchemyConversationRepository, SqlAlchemyAgentRunRepository],
) -> None:
    conversations, runs = repos
    message = inbound()
    first = await conversations.receive(TENANT_A_CTX, message)
    first_run = await runs.start(
        TENANT_A_CTX,
        conversation_id=first.conversation.id,
        input_message_id=first.message.id,
    )
    second = await conversations.receive(TENANT_A_CTX, message)
    second_run = await runs.start(
        TENANT_A_CTX,
        conversation_id=second.conversation.id,
        input_message_id=second.message.id,
    )
    assert second.duplicate is True
    assert first.duplicate is False
    assert second.message.id == first.message.id
    assert second.conversation.id == first.conversation.id
    assert second_run.id == first_run.id
    engine = create_async_engine(DATABASE_URL)
    try:
        async with engine.connect() as connection:
            message_count = await connection.scalar(
                select(func.count())
                .select_from(message_table)
                .where(message_table.c.tenant_id == TENANT_A)
            )
            run_count = await connection.scalar(
                select(func.count())
                .select_from(agent_run_table)
                .where(agent_run_table.c.tenant_id == TENANT_A)
            )
    finally:
        await engine.dispose()
    assert message_count == 1
    assert run_count == 1


@pytest.mark.anyio
@pytest.mark.integration
async def test_agent_run_captures_config_version_and_correlation_id(
    repos: tuple[SqlAlchemyConversationRepository, SqlAlchemyAgentRunRepository],
) -> None:
    conversations, runs = repos
    received = await conversations.receive(TENANT_A_CTX, inbound())
    run = await runs.start(
        TENANT_A_CTX,
        conversation_id=received.conversation.id,
        input_message_id=received.message.id,
    )
    assert run.config_version == TENANT_A_CTX.config_version
    assert run.correlation_id == TENANT_A_CTX.correlation_id
    loaded = await runs.get(TENANT_A_CTX, run.id)
    assert loaded is not None
    assert loaded.config_version == 1
    assert loaded.correlation_id == CORR_A
    assert loaded.status == "started"


@pytest.mark.anyio
@pytest.mark.integration
async def test_session_cas_rejects_stale_version(
    repos: tuple[SqlAlchemyConversationRepository, SqlAlchemyAgentRunRepository],
) -> None:
    conversations, _runs = repos
    received = await conversations.receive(TENANT_A_CTX, inbound())
    updated = await conversations.cas_update_session(
        TENANT_A_CTX,
        received.conversation.id,
        expected_version=received.session.state_version,
        active_skill="faq",
    )
    assert updated.active_skill == "faq"
    assert updated.state_version == received.session.state_version + 1
    with pytest.raises(ConversationError) as exc_info:
        await conversations.cas_update_session(
            TENANT_A_CTX,
            received.conversation.id,
            expected_version=received.session.state_version,
            active_skill="appointments",
        )
    assert exc_info.value.code == "conflict"
    session = await conversations.get_session(TENANT_A_CTX, received.conversation.id)
    assert session is not None
    assert session.active_skill == "faq"
    assert session.state_version == updated.state_version


@pytest.mark.anyio
@pytest.mark.integration
async def test_runtime_error_is_audited_with_safe_response(
    repos: tuple[SqlAlchemyConversationRepository, SqlAlchemyAgentRunRepository],
) -> None:
    conversations, runs = repos
    received = await conversations.receive(TENANT_A_CTX, inbound())
    run = await runs.start(
        TENANT_A_CTX,
        conversation_id=received.conversation.id,
        input_message_id=received.message.id,
    )
    result = await runs.finish(
        TENANT_A_CTX,
        run.id,
        status="failed",
        error_code="upstream_timeout",
        error_detail="password=supersecret stack=Traceback secret://db",
    )
    assert result.run.status == "failed"
    assert result.run.error_code == "upstream_timeout"
    assert result.safe_message == "An internal error occurred"
    assert "supersecret" not in result.safe_message
    assert result.safe_message is not None
    engine = create_async_engine(DATABASE_URL)
    try:
        async with engine.connect() as connection:
            stored = (
                (
                    await connection.execute(
                        select(agent_run_table).where(
                            agent_run_table.c.tenant_id == TENANT_A,
                            agent_run_table.c.id == run.id,
                        )
                    )
                )
                .mappings()
                .one()
            )
            assert stored["error_code"] == "upstream_timeout"
            usage = stored["usage"] or {}
            dumped = str(stored) + str(usage)
            assert "supersecret" not in dumped
            assert "password=" not in dumped
            actions = (
                (
                    await connection.execute(
                        select(audit_event_table.c.action).where(
                            audit_event_table.c.tenant_id == TENANT_A
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert "agent_run_failed" in actions
    finally:
        await engine.dispose()


@pytest.mark.anyio
@pytest.mark.integration
async def test_tenant_b_cannot_read_tenant_a_conversation_or_session(
    repos: tuple[SqlAlchemyConversationRepository, SqlAlchemyAgentRunRepository],
) -> None:
    conversations, runs = repos
    received = await conversations.receive(TENANT_A_CTX, inbound())
    run = await runs.start(
        TENANT_A_CTX,
        conversation_id=received.conversation.id,
        input_message_id=received.message.id,
    )
    assert await conversations.get(TENANT_B_CTX, received.conversation.id) is None
    assert (
        await conversations.get_session(TENANT_B_CTX, received.conversation.id) is None
    )
    assert await conversations.get_message(TENANT_B_CTX, received.message.id) is None
    assert await runs.get(TENANT_B_CTX, run.id) is None


@pytest.mark.integration
def test_conversations_migration_up_and_down() -> None:
    _reset_schema()
    alembic_cfg = Config(str(ROOT / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(ROOT / "alembic"))
    alembic_cfg.set_main_option("sqlalchemy.url", DATABASE_URL)
    engine = create_engine(DATABASE_URL)
    with engine.connect() as connection:
        tables = set(
            connection.execute(
                text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
            )
            .scalars()
            .all()
        )
    engine.dispose()
    assert {"conversation", "message", "session_state", "agent_run"} <= tables
    command.downgrade(alembic_cfg, "0001_foundations")
    engine = create_engine(DATABASE_URL)
    with engine.connect() as connection:
        tables = set(
            connection.execute(
                text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
            )
            .scalars()
            .all()
        )
    engine.dispose()
    assert "conversation" not in tables
    assert "message" not in tables
    assert "session_state" not in tables
    assert "agent_run" not in tables
    assert "tenant" in tables
    command.upgrade(alembic_cfg, "head")
