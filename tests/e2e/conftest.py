from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import command
from ia_mcp.agent_runtime.context_compiler import ContextCompiler
from ia_mcp.agent_runtime.harness import AgentHarness
from ia_mcp.agent_runtime.models import LLMDecision, LLMRequest
from ia_mcp.agent_runtime.run_repository import SqlAlchemyAgentRunRepository
from ia_mcp.api.app import create_app
from ia_mcp.channels.outbox import ChannelOutbox
from ia_mcp.configuration.adapters.sqlalchemy import (
    SqlAlchemyConfigRepository,
    channel_integration_table,
    tenant_table,
)
from ia_mcp.configuration.models import (
    AgentConfig,
    TenantAdminContext,
    TenantConfigDraft,
)
from ia_mcp.configuration.service import ConfigurationService
from ia_mcp.conversation.adapters.sqlalchemy import SqlAlchemyConversationRepository
from ia_mcp.knowledge.adapters.object_store import InMemoryObjectStore
from ia_mcp.knowledge.adapters.sqlalchemy import SqlAlchemyKnowledgeRepository
from ia_mcp.knowledge.models import DocumentSource
from ia_mcp.knowledge.service import KnowledgeService
from ia_mcp.skills.registry import SkillRegistry
from ia_mcp.tenancy.models import ChannelIntegration, TenantContext, TenantIdentity
from ia_mcp.tenancy.service import TenantService
from tests.integration.api.test_simulated_messages import signed_simulated_headers
from tests.unit.knowledge.fakes import FakeChunker, FakeEmbedding, FakeParser

ROOT = Path(__file__).resolve().parents[2]
DATABASE_URL = "postgresql+psycopg://francojimenez@127.0.0.1:5432/ia_mcp_p02_t03"

TENANT_A = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
TENANT_B = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
CHANNEL_A = UUID("aa111111-1111-1111-1111-111111111111")
CHANNEL_B = UUID("bb111111-1111-1111-1111-111111111111")
CORR_SHARED = UUID("55555555-5555-5555-5555-555555555555")
FROZEN_NOW = datetime(2026, 8, 28, 4, 20, 0, tzinfo=UTC)
CANARY_A = b"canary-a clinic hours eight to sixteen"
CANARY_B = b"canary-b night hours closed exclusive"
APPOINTMENT_TOOLS = frozenset(
    {
        "appointments.search",
        "appointments.get",
        "appointments.create",
        "appointments.cancel",
        "appointments.reschedule",
        "appointments.confirm",
    }
)


class FakeChannelRepository:
    def __init__(self, mapping: dict[tuple[str, str], tuple[UUID, str]]) -> None:
        self._mapping = mapping

    async def get(self, channel: str, account_id: str) -> ChannelIntegration | None:
        found = self._mapping.get((channel, account_id))
        if found is None:
            return None
        tenant_id, slug = found
        return ChannelIntegration(tenant_id=tenant_id, tenant_slug=slug, enabled=True)


class GroundedFakeLLM:
    async def generate(self, request: LLMRequest) -> LLMDecision:
        if not request.allowed_source_ids:
            return LLMDecision(kind="insufficient", text="", source_ids=())
        snippet = request.knowledge[0] if request.knowledge else ""
        return LLMDecision(
            kind="answer",
            text=snippet,
            source_ids=(request.allowed_source_ids[0],),
        )


class MutableClock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def tick(self) -> None:
        self.now = self.now + timedelta(seconds=1)


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


def _admin(identity: TenantIdentity) -> TenantAdminContext:
    return TenantAdminContext(
        identity=identity,
        principal_id=uuid4(),
        roles=frozenset({"admin"}),
        correlation_id=CORR_SHARED,
    )


@dataclass(frozen=True, slots=True)
class FaqRuntime:
    client: AsyncClient
    outbox: ChannelOutbox
    clock: MutableClock
    harness: AgentHarness
    compiler: ContextCompiler


@pytest.fixture
async def faq_runtime() -> AsyncIterator[FaqRuntime]:
    _reset_schema()
    _seed_tenants_and_channels()
    engine = create_async_engine(DATABASE_URL)
    config_repo = SqlAlchemyConfigRepository(engine)
    configs = ConfigurationService(config_repo)
    for identity, tone in (
        (TenantIdentity(TENANT_A, "tenant-a"), "cordial"),
        (TenantIdentity(TENANT_B, "tenant-b"), "formal"),
    ):
        published = await configs.publish(
            _admin(identity),
            TenantConfigDraft(
                agent=AgentConfig(tone=tone),
                enabled_skills=frozenset({"faq"}),
            ),
        )
        await configs.activate(_admin(identity), int(published.version))
    knowledge = KnowledgeService(
        repository=SqlAlchemyKnowledgeRepository(engine),
        parser=FakeParser(),
        chunker=FakeChunker(),
        embeddings=FakeEmbedding(),
        object_store=InMemoryObjectStore(),
    )
    ctx_a = TenantContext(
        tenant_id=TENANT_A,
        tenant_slug="tenant-a",
        config_version=1,
        correlation_id=CORR_SHARED,
    )
    ctx_b = TenantContext(
        tenant_id=TENANT_B,
        tenant_slug="tenant-b",
        config_version=1,
        correlation_id=CORR_SHARED,
    )
    draft_a = await knowledge.ingest(
        ctx_a, DocumentSource(filename="a.pdf", payload=CANARY_A)
    )
    draft_b = await knowledge.ingest(
        ctx_b, DocumentSource(filename="b.pdf", payload=CANARY_B)
    )
    await knowledge.publish(ctx_a, draft_a.document_id, draft_a.version)
    await knowledge.publish(ctx_b, draft_b.document_id, draft_b.version)

    clock = MutableClock(FROZEN_NOW)
    outbox = ChannelOutbox()
    skills = SkillRegistry()
    compiler = ContextCompiler(
        configs=config_repo,
        skills=skills,
        tenant_tools={TENANT_A: APPOINTMENT_TOOLS, TENANT_B: APPOINTMENT_TOOLS},
    )
    harness = AgentHarness(
        conversations=SqlAlchemyConversationRepository(engine),
        runs=SqlAlchemyAgentRunRepository(engine),
        configs=config_repo,
        skills=skills,
        compiler=compiler,
        knowledge=knowledge,
        llm=GroundedFakeLLM(),
    )
    app = create_app(environment="test")
    app.state.outbox = outbox
    app.state.agent_harness = harness
    app.state.config_service = configs
    app.state.tenant_service = TenantService(
        FakeChannelRepository(
            {
                ("simulated", "acct-a"): (TENANT_A, "tenant-a"),
                ("simulated", "acct-b"): (TENANT_B, "tenant-b"),
            }
        )
    )
    app.state.channel_integration_ids = {
        ("simulated", "acct-a"): CHANNEL_A,
        ("simulated", "acct-b"): CHANNEL_B,
    }
    app.state.simulated_clock = clock
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        try:
            yield FaqRuntime(
                client=client,
                outbox=outbox,
                clock=clock,
                harness=harness,
                compiler=compiler,
            )
        finally:
            await engine.dispose()


@pytest.fixture
async def faq_stack(
    faq_runtime: FaqRuntime,
) -> AsyncIterator[tuple[AsyncClient, ChannelOutbox, MutableClock]]:
    yield faq_runtime.client, faq_runtime.outbox, faq_runtime.clock


async def post_faq(
    client: AsyncClient,
    *,
    account: str,
    text: str,
    external_message_id: str,
    now: datetime,
    correlation_id: UUID = CORR_SHARED,
):
    body = {
        "external_message_id": external_message_id,
        "external_user_id": f"user-{account}",
        "text": text,
    }
    headers = signed_simulated_headers(account=account, body=body, now=now)
    headers["X-Correlation-ID"] = str(correlation_id)
    return await client.post("/v1/simulated/messages", json=body, headers=headers)
