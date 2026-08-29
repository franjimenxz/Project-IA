from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from alembic import command
from ia_mcp.configuration.adapters.sqlalchemy import (
    channel_integration_table,
    tenant_table,
)
from ia_mcp.conversation.adapters.sqlalchemy import SqlAlchemyConversationRepository
from ia_mcp.conversation.models import InboundMessage
from ia_mcp.handoff.adapters.fake import FakeHandoffAdapter
from ia_mcp.handoff.models import HandoffRequest
from ia_mcp.handoff.service import HandoffService, SqlAlchemyHandoffRepository
from ia_mcp.tenancy.models import TenantContext
from ia_mcp.workflows.adapters.sqlalchemy import outbox_event_table
from tests.fixtures.database import DATABASE_URL

ROOT = Path(__file__).resolve().parents[3]

TENANT_A = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
TENANT_B = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
CHANNEL_A = UUID("aa111111-1111-1111-1111-111111111111")
CHANNEL_B = UUID("bb111111-1111-1111-1111-111111111111")
OCCURRED_AT = datetime(2026, 8, 28, 4, 20, tzinfo=UTC)
TENANT_A_CTX = TenantContext(
    tenant_id=TENANT_A,
    tenant_slug="tenant-a",
    config_version=1,
    correlation_id=UUID("33333333-3333-3333-3333-333333333333"),
)
TENANT_B_CTX = TenantContext(
    tenant_id=TENANT_B,
    tenant_slug="tenant-b",
    config_version=1,
    correlation_id=UUID("44444444-4444-4444-4444-444444444444"),
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


class Harness:
    def __init__(
        self,
        db: AsyncEngine,
        conversations: SqlAlchemyConversationRepository,
        handoffs: HandoffService,
        repository: SqlAlchemyHandoffRepository,
        provider: FakeHandoffAdapter,
    ) -> None:
        self.db = db
        self.conversations = conversations
        self.handoffs = handoffs
        self.repository = repository
        self.provider = provider


@pytest.fixture
async def harness() -> AsyncIterator[Harness]:
    _reset_schema()
    _seed_tenants_and_channels()
    db = create_async_engine(DATABASE_URL)
    conversations = SqlAlchemyConversationRepository(db)
    repository = SqlAlchemyHandoffRepository(db)
    provider = FakeHandoffAdapter()
    try:
        yield Harness(
            db,
            conversations,
            HandoffService(repository, provider),
            repository,
            provider,
        )
    finally:
        await db.dispose()


async def _open_conversation(
    conversations: SqlAlchemyConversationRepository,
    tenant: TenantContext,
    *,
    channel_id: UUID,
    account: str,
    user: str,
    external_id: str,
) -> UUID:
    received = await conversations.receive(
        tenant,
        InboundMessage(
            channel="simulated",
            channel_account_id=account,
            channel_integration_id=channel_id,
            external_message_id=external_id,
            external_user_id=user,
            text="need a person",
            occurred_at=OCCURRED_AT,
        ),
    )
    return received.conversation.id


@pytest.mark.anyio
@pytest.mark.integration
async def test_handoff_and_human_owned_occur_together_and_replay(harness: Harness) -> None:
    conversation_id = await _open_conversation(
        harness.conversations,
        TENANT_A_CTX,
        channel_id=CHANNEL_A,
        account="acct-a",
        user="user-a",
        external_id="ext-1",
    )
    request = HandoffRequest(
        conversation_id=conversation_id,
        reason="explicit_request",
        business_key=f"handoff:{conversation_id}",
        collected_fields={"name": "Ana", "password": "supersecret"},
        completed_actions=("clarify",),
    )
    first = await harness.handoffs.create(TENANT_A_CTX, request)
    second = await harness.handoffs.create(TENANT_A_CTX, request)
    loaded = await harness.conversations.get(TENANT_A_CTX, conversation_id)
    assert loaded is not None
    assert loaded.status == "human_owned"
    assert first.reason == "explicit_request"
    assert second.handoff_id == first.handoff_id
    assert second.replayed is True
    assert await harness.repository.count_cases(TENANT_A_CTX) == 1
    async with harness.db.connect() as connection:
        outbox_count = await connection.scalar(
            select(func.count())
            .select_from(outbox_event_table)
            .where(
                outbox_event_table.c.tenant_id == TENANT_A,
                outbox_event_table.c.kind == "handoff.requested",
            )
        )
    assert outbox_count == 1


@pytest.mark.anyio
@pytest.mark.integration
async def test_payload_sanitized_and_provider_down_keeps_outbox() -> None:
    _reset_schema()
    _seed_tenants_and_channels()
    db = create_async_engine(DATABASE_URL)
    conversations = SqlAlchemyConversationRepository(db)
    repository = SqlAlchemyHandoffRepository(db)
    provider = FakeHandoffAdapter(available=False)
    service = HandoffService(repository, provider)
    try:
        conversation_id = await _open_conversation(
            conversations,
            TENANT_A_CTX,
            channel_id=CHANNEL_A,
            account="acct-a",
            user="user-a",
            external_id="ext-down",
        )
        result = await service.create(
            TENANT_A_CTX,
            HandoffRequest(
                conversation_id=conversation_id,
                reason="persistent_error",
                business_key=f"handoff:{conversation_id}",
                collected_fields={"note": "ok", "password": "supersecret"},
                notes="mail me at leak@example.com",
            ),
        )
        assert result.delivery_pending is True
        loaded = await conversations.get(TENANT_A_CTX, conversation_id)
        assert loaded is not None
        assert loaded.status == "human_owned"
        assert provider.cases_for(TENANT_A_CTX) == ()
        async with db.connect() as connection:
            rows = (
                (
                    await connection.execute(
                        select(outbox_event_table).where(
                            outbox_event_table.c.tenant_id == TENANT_A,
                            outbox_event_table.c.kind == "handoff.requested",
                        )
                    )
                )
                .mappings()
                .all()
            )
        assert len(rows) == 1
        dumped = str(rows[0]["payload"])
        assert "supersecret" not in dumped
        assert "password" not in dumped
        assert "leak@example.com" not in dumped
    finally:
        await db.dispose()


@pytest.mark.anyio
@pytest.mark.integration
async def test_tenant_b_cannot_read_tenant_a_handoff(harness: Harness) -> None:
    conversation_id = await _open_conversation(
        harness.conversations,
        TENANT_A_CTX,
        channel_id=CHANNEL_A,
        account="acct-a",
        user="user-a",
        external_id="ext-iso",
    )
    result = await harness.handoffs.create(
        TENANT_A_CTX,
        HandoffRequest(
            conversation_id=conversation_id,
            reason="policy",
            business_key=f"handoff:{conversation_id}",
        ),
    )
    assert await harness.repository.get(TENANT_B_CTX, result.handoff_id) is None
    assert (
        await harness.repository.get_by_business_key(
            TENANT_B_CTX, f"handoff:{conversation_id}"
        )
        is None
    )
    assert harness.provider.cases_for(TENANT_B_CTX) == ()


@pytest.mark.integration
def test_handoff_migration_up_and_down() -> None:
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
    assert {"handoff", "outbox_event", "conversation", "workflow_execution"} <= tables
    command.downgrade(alembic_cfg, "0004_workflows")
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
    assert "handoff" not in tables
    assert "workflow_execution" in tables
    assert "outbox_event" in tables
    command.upgrade(alembic_cfg, "head")
