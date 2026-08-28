from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic.config import Config
from pydantic import SecretStr
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import command
from ia_mcp.agent_runtime.run_repository import SqlAlchemyAgentRunRepository
from ia_mcp.configuration.adapters.sqlalchemy import (
    channel_integration_table,
    tenant_table,
)
from ia_mcp.configuration.models import AgentConfig, AppointmentPolicy, TenantConfig
from ia_mcp.contracts.appointments import (
    AppointmentCreateRequest,
    AppointmentGetRequest,
    AppointmentSlot,
    AppointmentStatus,
    PatientRef,
)
from ia_mcp.conversation.adapters.sqlalchemy import SqlAlchemyConversationRepository
from ia_mcp.conversation.models import InboundMessage
from ia_mcp.handoff.adapters.fake import FakeHandoffAdapter
from ia_mcp.handoff.models import HandoffRequest
from ia_mcp.handoff.service import HandoffService, SqlAlchemyHandoffRepository
from ia_mcp.knowledge.adapters.object_store import InMemoryObjectStore
from ia_mcp.knowledge.adapters.sqlalchemy import SqlAlchemyKnowledgeRepository
from ia_mcp.knowledge.models import DocumentSource, KnowledgeQuery
from ia_mcp.knowledge.ports import KnowledgeError
from ia_mcp.knowledge.service import KnowledgeService
from ia_mcp.mcp.executor import ToolExecutor
from ia_mcp.mcp.fakes.appointments import FakeAppointmentCapability
from ia_mcp.tenancy.models import TenantContext
from ia_mcp.workflows.appointments.cancel import CancelAppointmentDefinition
from ia_mcp.workflows.engine import WorkflowEngine
from tests.unit.knowledge.fakes import FakeChunker, FakeEmbedding, FakeParser
from tests.unit.workflows.fakes import InMemoryWorkflowRepository

ROOT = Path(__file__).resolve().parents[2]
DATABASE_URL = "postgresql+psycopg://francojimenez@127.0.0.1:5432/ia_mcp_p02_t03"

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


@pytest.fixture
async def repos() -> AsyncIterator[
    tuple[SqlAlchemyConversationRepository, SqlAlchemyAgentRunRepository]
]:
    _reset_schema()
    _seed_tenants_and_channels()
    engine = create_async_engine(DATABASE_URL)
    try:
        yield (
            SqlAlchemyConversationRepository(engine),
            SqlAlchemyAgentRunRepository(engine),
        )
    finally:
        await engine.dispose()


@pytest.mark.anyio
@pytest.mark.security
async def test_conversation_and_session_a_are_not_found_under_tenant_b(
    repos: tuple[SqlAlchemyConversationRepository, SqlAlchemyAgentRunRepository],
) -> None:
    conversations, runs = repos
    received = await conversations.receive(
        TENANT_A_CTX,
        InboundMessage(
            channel="simulated",
            channel_account_id="acct-a",
            channel_integration_id=CHANNEL_A,
            external_message_id="ext-msg-a",
            external_user_id="user-a",
            text="canary-from-tenant-a",
            occurred_at=OCCURRED_AT,
        ),
    )
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


@pytest.mark.anyio
@pytest.mark.security
async def test_tenant_b_receive_does_not_attach_to_tenant_a_conversation(
    repos: tuple[SqlAlchemyConversationRepository, SqlAlchemyAgentRunRepository],
) -> None:
    conversations, _runs = repos
    received_a = await conversations.receive(
        TENANT_A_CTX,
        InboundMessage(
            channel="simulated",
            channel_account_id="acct-a",
            channel_integration_id=CHANNEL_A,
            external_message_id="shared-external-id",
            external_user_id="same-user-label",
            text="canary-from-tenant-a",
            occurred_at=OCCURRED_AT,
        ),
    )
    received_b = await conversations.receive(
        TENANT_B_CTX,
        InboundMessage(
            channel="simulated",
            channel_account_id="acct-b",
            channel_integration_id=CHANNEL_B,
            external_message_id="shared-external-id",
            external_user_id="same-user-label",
            text="canary-from-tenant-b",
            occurred_at=OCCURRED_AT,
        ),
    )
    assert received_b.conversation.id != received_a.conversation.id
    assert received_b.message.id != received_a.message.id
    loaded_a = await conversations.get(TENANT_A_CTX, received_b.conversation.id)
    loaded_b = await conversations.get(TENANT_B_CTX, received_a.conversation.id)
    assert loaded_a is None
    assert loaded_b is None
    message_a = await conversations.get_message(TENANT_A_CTX, received_a.message.id)
    message_b = await conversations.get_message(TENANT_B_CTX, received_b.message.id)
    assert message_a is not None
    assert message_b is not None
    assert message_a.id != message_b.id



@pytest.fixture
async def knowledge_service() -> AsyncIterator[KnowledgeService]:
    _reset_schema()
    _seed_tenants_and_channels()
    engine = create_async_engine(DATABASE_URL)
    try:
        yield KnowledgeService(
            repository=SqlAlchemyKnowledgeRepository(engine),
            parser=FakeParser(),
            chunker=FakeChunker(),
            embeddings=FakeEmbedding(),
            object_store=InMemoryObjectStore(),
        )
    finally:
        await engine.dispose()


@pytest.mark.anyio
@pytest.mark.security
async def test_search_under_a_never_returns_tenant_b_canary_chunk(
    knowledge_service: KnowledgeService,
) -> None:
    draft_a = await knowledge_service.ingest(
        TENANT_A_CTX,
        DocumentSource(filename="a.pdf", payload=b"canary-a clinic hours"),
    )
    draft_b = await knowledge_service.ingest(
        TENANT_B_CTX,
        DocumentSource(filename="b.pdf", payload=b"canary-b exclusive secret"),
    )
    await knowledge_service.publish(TENANT_A_CTX, draft_a.document_id, draft_a.version)
    await knowledge_service.publish(TENANT_B_CTX, draft_b.document_id, draft_b.version)
    hits = await knowledge_service.search(
        TENANT_A_CTX, KnowledgeQuery(text="canary-b exclusive", limit=10)
    )
    assert all(hit.tenant_id == TENANT_A for hit in hits)
    assert all("canary-b" not in hit.text for hit in hits)


@pytest.mark.anyio
@pytest.mark.security
async def test_tenant_a_cannot_publish_tenant_b_document(
    knowledge_service: KnowledgeService,
) -> None:
    draft_b = await knowledge_service.ingest(
        TENANT_B_CTX,
        DocumentSource(filename="b.pdf", payload=b"canary-b exclusive secret"),
    )
    with pytest.raises(KnowledgeError):
        await knowledge_service.publish(
            TENANT_A_CTX, draft_b.document_id, draft_b.version
        )


@pytest.mark.anyio
@pytest.mark.security
async def test_operator_of_a_does_not_receive_case_b(
    repos: tuple[SqlAlchemyConversationRepository, SqlAlchemyAgentRunRepository],
) -> None:
    conversations, _runs = repos
    received_b = await conversations.receive(
        TENANT_B_CTX,
        InboundMessage(
            channel="simulated",
            channel_account_id="acct-b",
            channel_integration_id=CHANNEL_B,
            external_message_id="ext-handoff-b",
            external_user_id="user-b",
            text="canary-handoff-from-b",
            occurred_at=OCCURRED_AT,
        ),
    )
    engine = create_async_engine(DATABASE_URL)
    try:
        repository = SqlAlchemyHandoffRepository(engine)
        provider = FakeHandoffAdapter()
        service = HandoffService(repository, provider)
        result = await service.create(
            TENANT_B_CTX,
            HandoffRequest(
                conversation_id=received_b.conversation.id,
                reason="explicit_request",
                business_key=f"handoff:{received_b.conversation.id}",
            ),
        )
        assert await repository.get(TENANT_A_CTX, result.handoff_id) is None
        assert (
            await repository.get_by_business_key(
                TENANT_A_CTX, f"handoff:{received_b.conversation.id}"
            )
            is None
        )
        assert provider.cases_for(TENANT_A_CTX) == ()
        b_cases = provider.cases_for(TENANT_B_CTX)
        assert len(b_cases) == 1
        assert b_cases[0].handoff_id == result.handoff_id
        assert b_cases[0].conversation_id == received_b.conversation.id
    finally:
        await engine.dispose()


@pytest.mark.anyio
@pytest.mark.security
async def test_tenant_a_cannot_cancel_tenant_b_appointment() -> None:
    capability = FakeAppointmentCapability(
        clock=lambda: datetime(2026, 9, 1, 12, tzinfo=UTC),
        id_factory=lambda: "appt-b-1",
        initial_slots={
            TENANT_B: (
                AppointmentSlot(
                    slot_id="slot-b-1",
                    starts_at=datetime(2026, 9, 1, 13, 0, tzinfo=UTC),
                    ends_at=datetime(2026, 9, 1, 13, 30, tzinfo=UTC),
                    specialty="cardiologia",
                    practitioner="Dr. Bravo Exclusive",
                    location="sede-norte-b",
                    booking_token=SecretStr("tok-b-secret"),
                ),
            )
        },
    )
    seeded = await capability.create(
        TENANT_B_CTX,
        AppointmentCreateRequest(
            slot_id="slot-b-1",
            booking_token=SecretStr("tok-b-secret"),
            patient=PatientRef(name="Bravo Patient", email="bravo@example.com"),
        ),
        idempotency_key="seed-b",
    )
    assert seeded.ok
    repository = InMemoryWorkflowRepository()
    definition = CancelAppointmentDefinition()
    engine = WorkflowEngine(repository, definition)
    executor = ToolExecutor(
        server=frozenset(
            {
                "appointments.search",
                "appointments.get",
                "appointments.create",
                "appointments.cancel",
                "appointments.reschedule",
                "appointments.confirm",
            }
        ),
        tenant=frozenset(
            {
                "appointments.search",
                "appointments.get",
                "appointments.create",
                "appointments.cancel",
                "appointments.reschedule",
                "appointments.confirm",
            }
        ),
        skill=frozenset({"appointments.get", "appointments.cancel"}),
        capability=capability,
    )
    config = TenantConfig(
        tenant_id=TENANT_A,
        version=1,
        agent=AgentConfig(tone="cordial"),
        enabled_skills=frozenset({"appointments"}),
        appointments=AppointmentPolicy(),
    )
    started = await definition.start(
        engine,
        TENANT_A_CTX,
        command_id="start-cross",
        config=config,
        appointment_id="appt-b-1",
    )
    looked = await definition.lookup(
        engine,
        executor,
        TENANT_A_CTX,
        started.workflow_id,
        command_id="lookup-cross",
        run_id=uuid4(),
        config=config,
    )
    missing_started = await definition.start(
        engine,
        TENANT_A_CTX,
        command_id="start-missing",
        config=config,
        appointment_id="appt-missing-id",
    )
    missing = await definition.lookup(
        engine,
        executor,
        TENANT_A_CTX,
        missing_started.workflow_id,
        command_id="lookup-missing",
        run_id=uuid4(),
        config=config,
    )
    assert looked.state == "failed"
    assert missing.state == "failed"
    assert looked.data.get("error") == missing.data.get("error")
    assert looked.error == missing.error
    blob = repr(looked.data) + repr(looked.error)
    assert str(TENANT_B) not in blob
    assert "Dr. Bravo Exclusive" not in blob
    assert "sede-norte-b" not in blob
    assert "Bravo Patient" not in blob
    assert "traceback" not in blob.lower()
    current = await capability.get(
        TENANT_B_CTX, AppointmentGetRequest(appointment_id="appt-b-1")
    )
    assert current.ok
    assert current.value is not None
    assert current.value.status is AppointmentStatus.SCHEDULED
