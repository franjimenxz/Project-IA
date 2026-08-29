from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import command
from ia_mcp.agent_runtime.context_compiler import ContextCompiler
from ia_mcp.agent_runtime.harness import AgentHarness
from ia_mcp.agent_runtime.models import LLMDecision
from ia_mcp.agent_runtime.ports import FakeLLM
from ia_mcp.agent_runtime.run_repository import SqlAlchemyAgentRunRepository
from ia_mcp.configuration.adapters.sqlalchemy import (
    channel_integration_table,
    tenant_table,
)
from ia_mcp.configuration.models import AgentConfig, TenantConfig
from ia_mcp.conversation.adapters.sqlalchemy import SqlAlchemyConversationRepository
from ia_mcp.conversation.models import InboundMessage
from ia_mcp.handoff.adapters.fake import FakeHandoffAdapter
from ia_mcp.handoff.models import HandoffRequest
from ia_mcp.handoff.service import HandoffService, SqlAlchemyHandoffRepository
from ia_mcp.knowledge.models import KnowledgeHit, KnowledgeQuery
from ia_mcp.skills.registry import SkillRegistry
from ia_mcp.tenancy.models import TenantContext
from tests.fixtures.database import DATABASE_URL

ROOT = Path(__file__).resolve().parents[2]

TENANT_A = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
TENANT_B = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
CHANNEL_A = UUID("aa111111-1111-1111-1111-111111111111")
CHANNEL_B = UUID("bb111111-1111-1111-1111-111111111111")
OCCURRED_AT = datetime(2026, 8, 28, 5, 0, tzinfo=UTC)
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


class RecordingKnowledge:
    def __init__(self) -> None:
        self.queries: list[KnowledgeQuery] = []

    async def search(
        self, tenant: TenantContext, query: KnowledgeQuery
    ) -> tuple[KnowledgeHit, ...]:
        del tenant
        self.queries.append(query)
        return ()


class StaticConfigs:
    async def get_for_runtime(self, context: TenantContext) -> TenantConfig | None:
        return TenantConfig(
            tenant_id=context.tenant_id,
            version=1,
            agent=AgentConfig(tone="cordial"),
            enabled_skills=frozenset({"faq"}),
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


def _seed() -> None:
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
async def stack() -> AsyncIterator[
    tuple[
        SqlAlchemyConversationRepository,
        HandoffService,
        FakeHandoffAdapter,
        AgentHarness,
        RecordingKnowledge,
        SqlAlchemyHandoffRepository,
    ]
]:
    _reset_schema()
    _seed()
    db = create_async_engine(DATABASE_URL)
    conversations = SqlAlchemyConversationRepository(db)
    runs = SqlAlchemyAgentRunRepository(db)
    repository = SqlAlchemyHandoffRepository(db)
    provider = FakeHandoffAdapter()
    service = HandoffService(repository, provider)
    knowledge = RecordingKnowledge()
    configs = StaticConfigs()
    harness = AgentHarness(
        conversations=conversations,
        runs=runs,
        configs=configs,
        skills=SkillRegistry(),
        compiler=ContextCompiler(
            configs=configs,
            skills=SkillRegistry(),
            tenant_tools={TENANT_A: frozenset({"appointments.create"})},
        ),
        knowledge=knowledge,
        llm=FakeLLM(
            LLMDecision(kind="answer", text="should not run", source_ids=("x",))
        ),
    )
    try:
        yield conversations, service, provider, harness, knowledge, repository
    finally:
        await db.dispose()


@pytest.mark.anyio
@pytest.mark.e2e
async def test_explicit_request_reaches_operator_fake(stack) -> None:  # type: ignore[no-untyped-def]
    conversations, service, provider, _harness, _knowledge, repository = stack
    received = await conversations.receive(
        TENANT_A_CTX,
        InboundMessage(
            channel="simulated",
            channel_account_id="acct-a",
            channel_integration_id=CHANNEL_A,
            external_message_id="ext-e2e-a",
            external_user_id="user-a",
            text="I want to talk to a person",
            occurred_at=OCCURRED_AT,
        ),
    )
    result = await service.create(
        TENANT_A_CTX,
        HandoffRequest(
            conversation_id=received.conversation.id,
            reason="explicit_request",
            business_key=f"handoff:{received.conversation.id}",
            collected_fields={"intent": "human"},
            completed_actions=("faq_insufficient",),
        ),
    )
    loaded = await conversations.get(TENANT_A_CTX, received.conversation.id)
    assert loaded is not None
    assert loaded.status == "human_owned"
    cases = provider.cases_for(TENANT_A_CTX)
    assert len(cases) == 1
    assert cases[0].handoff_id == result.handoff_id
    assert cases[0].reason == "explicit_request"
    assert await repository.count_cases(TENANT_A_CTX) == 1


@pytest.mark.anyio
@pytest.mark.e2e
async def test_human_owned_blocks_mutations_after_handoff(stack) -> None:  # type: ignore[no-untyped-def]
    conversations, service, _provider, harness, knowledge, _repository = stack
    first = await conversations.receive(
        TENANT_A_CTX,
        InboundMessage(
            channel="simulated",
            channel_account_id="acct-a",
            channel_integration_id=CHANNEL_A,
            external_message_id="ext-e2e-first",
            external_user_id="user-guard",
            text="please transfer me",
            occurred_at=OCCURRED_AT,
        ),
    )
    await service.create(
        TENANT_A_CTX,
        HandoffRequest(
            conversation_id=first.conversation.id,
            reason="explicit_request",
            business_key=f"handoff:{first.conversation.id}",
        ),
    )
    result = await harness.handle_message(
        TENANT_A_CTX,
        InboundMessage(
            channel="simulated",
            channel_account_id="acct-a",
            channel_integration_id=CHANNEL_A,
            external_message_id="ext-e2e-second",
            external_user_id="user-guard",
            text="create appointment now",
            occurred_at=OCCURRED_AT,
        ),
    )
    assert result.kind == "handoff"
    assert result.tool_names == ()
    assert knowledge.queries == []
    assert "guard" in result.trajectory
    owned = await conversations.get(TENANT_A_CTX, first.conversation.id)
    assert owned is not None
    assert owned.status == "human_owned"


@pytest.mark.anyio
@pytest.mark.e2e
async def test_two_tenants_operator_inboxes_are_isolated(stack) -> None:  # type: ignore[no-untyped-def]
    conversations, service, provider, _harness, _knowledge, _repository = stack
    received_a = await conversations.receive(
        TENANT_A_CTX,
        InboundMessage(
            channel="simulated",
            channel_account_id="acct-a",
            channel_integration_id=CHANNEL_A,
            external_message_id="ext-e2e-iso-a",
            external_user_id="user-a",
            text="help a",
            occurred_at=OCCURRED_AT,
        ),
    )
    received_b = await conversations.receive(
        TENANT_B_CTX,
        InboundMessage(
            channel="simulated",
            channel_account_id="acct-b",
            channel_integration_id=CHANNEL_B,
            external_message_id="ext-e2e-iso-b",
            external_user_id="user-b",
            text="help b",
            occurred_at=OCCURRED_AT,
        ),
    )
    await service.create(
        TENANT_A_CTX,
        HandoffRequest(
            conversation_id=received_a.conversation.id,
            reason="out_of_scope",
            business_key="handoff:a",
        ),
    )
    await service.create(
        TENANT_B_CTX,
        HandoffRequest(
            conversation_id=received_b.conversation.id,
            reason="policy",
            business_key="handoff:b",
        ),
    )
    a_cases = provider.cases_for(TENANT_A_CTX)
    b_cases = provider.cases_for(TENANT_B_CTX)
    assert len(a_cases) == 1
    assert len(b_cases) == 1
    assert a_cases[0].conversation_id == received_a.conversation.id
    assert b_cases[0].conversation_id == received_b.conversation.id
    assert a_cases[0].handoff_id != b_cases[0].handoff_id
