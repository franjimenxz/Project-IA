from __future__ import annotations

import importlib
import inspect
from collections.abc import AsyncIterator
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from pydantic import SecretStr, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine

from ia_mcp.agent_runtime.context_compiler import ContextCompiler
from ia_mcp.agent_runtime.context_models import ContextRequest
from ia_mcp.agent_runtime.run_repository import SqlAlchemyAgentRunRepository
from ia_mcp.configuration.adapters.sqlalchemy import (
    SqlAlchemyConfigRepository,
    audit_event_table,
)
from ia_mcp.configuration.models import (
    AgentConfig,
    AppointmentPolicy,
    TenantAdminContext,
    TenantConfig,
    TenantConfigDraft,
)
from ia_mcp.configuration.ports import ConfigRepository, ConfigurationError
from ia_mcp.configuration.service import ConfigurationService
from ia_mcp.contracts.appointments import (
    AppointmentCreateRequest,
    AppointmentGetRequest,
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
from ia_mcp.scheduling.models import (
    JOB_TYPE,
    AppointmentScheduledEvent,
    SchedulingPolicy,
)
from ia_mcp.scheduling.service import ReminderScheduler, SqlAlchemyJobStore
from ia_mcp.skills.registry import SkillRegistry
from ia_mcp.tenancy.models import TenantContext, TenantIdentity
from ia_mcp.workflows.adapters.sqlalchemy import SqlAlchemyWorkflowRepository
from ia_mcp.workflows.appointments.cancel import CancelAppointmentDefinition
from ia_mcp.workflows.appointments.create import CreateAppointmentDefinition
from ia_mcp.workflows.engine import WorkflowEngine
from ia_mcp.workflows.models import AdvanceCommand
from ia_mcp.workflows.ports import WorkflowError
from tests.fixtures.security_matrix import (
    ALL_TOOLS,
    CANARY_B_LOCATION,
    CANARY_B_PATIENT,
    CANARY_B_PRACTITIONER,
    CAPABILITY_CLOCK,
    CHANNEL_A,
    CHANNEL_B,
    DATABASE_URL,
    ISOLATION_LEGS,
    OCCURRED_AT,
    SECRET_REFERENCE_A,
    SECRET_REFERENCE_B,
    SECRET_VALUE,
    SECURITY_MATRIX,
    SLOT_STARTS_AT,
    TENANT_A,
    TENANT_A_ADMIN_CTX,
    TENANT_A_CTX,
    TENANT_B,
    TENANT_B_ADMIN_CTX,
    TENANT_B_CTX,
    TENANT_B_IDENTITY,
    config_draft,
    reset_schema,
    seed_tenants_and_channels,
    two_tenant_capability,
)
from tests.unit.knowledge.fakes import FakeChunker, FakeEmbedding, FakeParser
from tests.unit.scheduling.fakes import AdjustableClock
from tests.unit.workflows.fakes import InMemoryWorkflowRepository


class _FakeConfigLookup:
    def __init__(self, configs: dict[UUID, TenantConfig]) -> None:
        self._configs = configs

    async def get_for_runtime(self, context: TenantContext) -> TenantConfig | None:
        return self._configs.get(context.tenant_id)


@pytest.fixture
async def repos() -> AsyncIterator[
    tuple[SqlAlchemyConversationRepository, SqlAlchemyAgentRunRepository]
]:
    reset_schema()
    seed_tenants_and_channels()
    engine = create_async_engine(DATABASE_URL)
    try:
        yield (
            SqlAlchemyConversationRepository(engine),
            SqlAlchemyAgentRunRepository(engine),
        )
    finally:
        await engine.dispose()


@pytest.mark.security
def test_security_matrix_covers_every_isolation_leg() -> None:
    covered = {row.leg for row in SECURITY_MATRIX}
    assert covered == ISOLATION_LEGS
    for row in SECURITY_MATRIX:
        module = importlib.import_module(row.module)
        case = getattr(module, row.test, None)
        assert callable(case), f"{row.module}::{row.test} is missing"
        markers = {mark.name for mark in getattr(case, "pytestmark", ())}
        assert "security" in markers, f"{row.module}::{row.test} lacks security mark"


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
    reset_schema()
    seed_tenants_and_channels()
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
async def test_object_key_of_a_is_rejected_under_tenant_b() -> None:
    store = InMemoryObjectStore()
    key_a = await store.put(TENANT_A_CTX, "doc-a/hours.pdf", b"canary-a payload")
    key_b = await store.put(TENANT_B_CTX, "doc-b/hours.pdf", b"canary-b payload")
    assert await store.get(TENANT_A_CTX, key_a) == b"canary-a payload"
    with pytest.raises(KnowledgeError) as caught:
        await store.get(TENANT_B_CTX, key_a)
    assert caught.value.code == "tenant_isolation_violation"
    assert "canary-a" not in str(caught.value)
    assert str(TENANT_A) not in caught.value.safe_message
    # A key crafted to look like tenant A's namespace still lands under B.
    spoofed = await store.put(TENANT_B_CTX, f"{TENANT_A}/doc-a/hours.pdf", b"spoof")
    assert spoofed.startswith(f"{TENANT_B}/")
    assert await store.get(TENANT_B_CTX, spoofed) == b"spoof"
    assert await store.get(TENANT_B_CTX, key_b) == b"canary-b payload"


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
async def test_workflow_state_of_a_is_invisible_to_tenant_b() -> None:
    reset_schema()
    seed_tenants_and_channels()
    engine = create_async_engine(DATABASE_URL)
    try:
        repository = SqlAlchemyWorkflowRepository(engine)
        definition = CreateAppointmentDefinition()
        workflows = WorkflowEngine(repository, definition)
        config = TenantConfig(
            tenant_id=TENANT_A,
            version=1,
            agent=AgentConfig(tone="cordial"),
            enabled_skills=frozenset({"appointments"}),
            appointments=AppointmentPolicy(required_fields=("specialty",)),
        )
        started = await definition.start(
            workflows,
            TENANT_A_CTX,
            command_id="start-a",
            config=config,
            idempotency_key="shared-idempotency-key",
        )
        await definition.collect_fields(
            workflows,
            TENANT_A_CTX,
            started.workflow_id,
            command_id="collect-a",
            fields={"specialty": "canary-a-specialty"},
            config=config,
        )
        assert await repository.get(TENANT_B_CTX, started.workflow_id) is None
        assert await repository.list_transitions(TENANT_B_CTX, started.workflow_id) == ()
        assert (
            await repository.get_transition(
                TENANT_B_CTX, started.workflow_id, "collect-a"
            )
            is None
        )
        assert await repository.count_transitions(
            TENANT_B_CTX, started.workflow_id
        ) == 0
        with pytest.raises(WorkflowError) as caught:
            await workflows.advance(
                TENANT_B_CTX,
                AdvanceCommand(
                    workflow_id=started.workflow_id,
                    command_id="hijack-b",
                    event_type="submit",
                ),
            )
        assert caught.value.code == "not_found"
        assert "canary-a-specialty" not in caught.value.safe_message
        # The shared idempotency key must not attach B to A's execution.
        hijacked = await definition.start(
            workflows,
            TENANT_B_CTX,
            command_id="start-b",
            config=config,
            idempotency_key="shared-idempotency-key",
        )
        assert hijacked.workflow_id != started.workflow_id
        a_state = await repository.get(TENANT_A_CTX, started.workflow_id)
        assert a_state is not None
        assert a_state.data.get("specialty") == "canary-a-specialty"
    finally:
        await engine.dispose()


@pytest.mark.anyio
@pytest.mark.security
async def test_active_config_of_a_is_unreachable_from_tenant_b() -> None:
    reset_schema()
    seed_tenants_and_channels()
    engine = create_async_engine(DATABASE_URL)
    try:
        repository = SqlAlchemyConfigRepository(engine)
        service = ConfigurationService(repository)
        await service.publish(
            TENANT_A_ADMIN_CTX,
            config_draft(tone="canary-a-tone", credentials_reference=SECRET_REFERENCE_A),
        )
        await service.activate(TENANT_A_ADMIN_CTX, 1)
        await service.publish(
            TENANT_B_ADMIN_CTX,
            config_draft(tone="canary-b-tone", credentials_reference=SECRET_REFERENCE_B),
        )
        await service.activate(TENANT_B_ADMIN_CTX, 1)
        active_b = await repository.get_active(TENANT_B_IDENTITY)
        assert active_b is not None
        assert active_b.tenant_id == TENANT_B
        assert active_b.agent.tone == "canary-b-tone"
        # An admin identity of B asking for a version by number gets B's row.
        version_b = await repository.get_version(TENANT_B_IDENTITY, 1)
        assert version_b is not None
        assert version_b.tenant_id == TENANT_B
        assert "canary-a-tone" not in str(version_b.model_dump(mode="json"))
        # A runtime context that mixes B's id with A's slug fails closed.
        mixed = TenantContext(
            tenant_id=TENANT_B,
            tenant_slug="tenant-a",
            config_version=1,
            correlation_id=uuid4(),
        )
        with pytest.raises(ConfigurationError) as caught:
            await repository.get_for_runtime(mixed)
        assert caught.value.code == "tenant_isolation_violation"
        assert "canary-a-tone" not in caught.value.safe_message
        assert "canary-b-tone" not in caught.value.safe_message
        # Capturing from an unregistered identity does not fall back to a peer.
        unknown = TenantIdentity(
            tenant_id=UUID("cccccccc-cccc-cccc-cccc-cccccccccccc"),
            tenant_slug="tenant-c",
        )
        with pytest.raises(ConfigurationError) as missing:
            await service.capture(unknown, uuid4())
        assert missing.value.code == "not_found"
        assert "canary-a-tone" not in missing.value.safe_message
    finally:
        await engine.dispose()


@pytest.mark.anyio
@pytest.mark.security
async def test_credentials_reference_is_tenant_scoped_and_never_holds_values() -> None:
    with pytest.raises(ValidationError):
        TenantConfigDraft.model_validate(
            {
                "agent": {"tone": "cordial"},
                "mcp": {
                    "credentials_reference": SECRET_REFERENCE_A,
                    "api_key": SECRET_VALUE,
                },
            }
        )
    reset_schema()
    seed_tenants_and_channels()
    engine = create_async_engine(DATABASE_URL)
    try:
        repository = SqlAlchemyConfigRepository(engine)
        service = ConfigurationService(repository)
        await service.publish(
            TENANT_A_ADMIN_CTX,
            config_draft(tone="cordial", credentials_reference=SECRET_REFERENCE_A),
        )
        await service.activate(TENANT_A_ADMIN_CTX, 1)
        await service.publish(
            TENANT_B_ADMIN_CTX,
            config_draft(tone="formal", credentials_reference=SECRET_REFERENCE_B),
        )
        await service.activate(TENANT_B_ADMIN_CTX, 1)
        config_a = await repository.get_for_runtime(TENANT_A_CTX)
        config_b = await repository.get_for_runtime(TENANT_B_CTX)
        assert config_a is not None
        assert config_b is not None
        assert config_a.mcp.credentials_reference == SECRET_REFERENCE_A
        assert config_b.mcp.credentials_reference == SECRET_REFERENCE_B
        assert SECRET_REFERENCE_A not in str(config_b.model_dump(mode="json"))
        assert SECRET_VALUE not in str(config_a.model_dump(mode="json"))
        # The reference is resolved outside the model: it never reaches a prompt.
        compiler = ContextCompiler(
            configs=_FakeConfigLookup({TENANT_A: config_a}),
            skills=SkillRegistry(),
            tenant_tools={TENANT_A: ALL_TOOLS},
        )
        compiled = await compiler.compile(
            TENANT_A_CTX, ContextRequest(skill="faq", history=("hola",))
        )
        blob = str(compiled.model_dump(mode="json"))
        assert SECRET_REFERENCE_A not in blob
        assert SECRET_REFERENCE_B not in blob
        assert "credentials_reference" not in blob
    finally:
        await engine.dispose()


@pytest.mark.anyio
@pytest.mark.security
async def test_reminder_job_of_a_is_invisible_and_immutable_from_b() -> None:
    reset_schema()
    seed_tenants_and_channels()
    engine = create_async_engine(DATABASE_URL)
    try:
        store = SqlAlchemyJobStore(engine)
        clock = AdjustableClock(CAPABILITY_CLOCK)
        scheduler = ReminderScheduler(
            store=store, clock=clock, policy=SchedulingPolicy()
        )
        event = AppointmentScheduledEvent(
            appointment_id="appt-shared-id", starts_at=SLOT_STARTS_AT
        )
        job_a = await scheduler.upsert(TENANT_A_CTX, event)
        business_key = f"{event.appointment_id}:{event.reminder_kind}"
        assert await store.get(TENANT_B_CTX, job_a.id) is None
        assert await store.get_by_identity(TENANT_B_CTX, JOB_TYPE, business_key) is None
        assert await store.has_outbox(TENANT_B_CTX, job_a.id, job_a.schedule_version) is (
            False
        )
        assert await scheduler.cancel(TENANT_B_CTX, event.appointment_id) is None
        # The same business key under B is a distinct job, not a takeover.
        job_b = await scheduler.upsert(TENANT_B_CTX, event)
        assert job_b.id != job_a.id
        assert job_b.tenant_id == TENANT_B
        assert job_b.schedule_version == 1
        reloaded_a = await store.get(TENANT_A_CTX, job_a.id)
        assert reloaded_a is not None
        assert reloaded_a.status == "pending"
        assert reloaded_a.schedule_version == 1
        assert reloaded_a.payload["tenant_slug"] == "tenant-a"
        assert "tenant-b" not in str(reloaded_a.payload)
        # Cancelling under A does not touch B's job.
        cancelled = await scheduler.cancel(TENANT_A_CTX, event.appointment_id)
        assert cancelled is not None
        assert cancelled.status == "cancelled"
        untouched_b = await store.get(TENANT_B_CTX, job_b.id)
        assert untouched_b is not None
        assert untouched_b.status == "pending"
        clock.advance(timedelta(days=365))
    finally:
        await engine.dispose()


@pytest.mark.anyio
@pytest.mark.security
async def test_audit_events_are_tenant_scoped_and_runtime_has_no_delete_api() -> None:
    reset_schema()
    seed_tenants_and_channels()
    engine = create_async_engine(DATABASE_URL)
    try:
        repository = SqlAlchemyConfigRepository(engine)
        service = ConfigurationService(repository)
        await service.publish(
            TENANT_A_ADMIN_CTX,
            config_draft(tone="cordial", credentials_reference=SECRET_REFERENCE_A),
        )
        await service.activate(TENANT_A_ADMIN_CTX, 1)
        await service.publish(
            TENANT_B_ADMIN_CTX,
            config_draft(tone="formal", credentials_reference=SECRET_REFERENCE_B),
        )
        async with engine.connect() as connection:
            rows_a = (
                await connection.execute(
                    select(
                        audit_event_table.c.actor_id,
                        audit_event_table.c.action,
                        audit_event_table.c.version,
                    ).where(audit_event_table.c.tenant_id == TENANT_A)
                )
            ).all()
            rows_b = (
                await connection.execute(
                    select(
                        audit_event_table.c.actor_id,
                        audit_event_table.c.action,
                    ).where(audit_event_table.c.tenant_id == TENANT_B)
                )
            ).all()
        actors_a = {row[0] for row in rows_a}
        actors_b = {row[0] for row in rows_b}
        assert actors_a == {TENANT_A_ADMIN_CTX.principal_id}
        assert actors_b == {TENANT_B_ADMIN_CTX.principal_id}
        assert actors_a.isdisjoint(actors_b)
        assert {(row[1], row[2]) for row in rows_a} == {("publish", 1), ("activate", 1)}
        assert {row[1] for row in rows_b} == {"publish"}
        # Audit writes belong to the admin port; runtime holds no mutation verb.
        signature = inspect.signature(SqlAlchemyConfigRepository.record_audit)
        first = list(signature.parameters.values())[1]
        assert first.annotation is TenantAdminContext
        mutating = {"delete", "purge", "remove", "truncate", "drop", "update_audit"}
        for surface in (SqlAlchemyConfigRepository, ConfigRepository):
            names = {name for name in dir(surface) if not name.startswith("_")}
            assert not {
                name for name in names if any(verb in name for verb in mutating)
            }
    finally:
        await engine.dispose()


@pytest.mark.anyio
@pytest.mark.security
async def test_tenant_a_cannot_cancel_tenant_b_appointment() -> None:
    capability = two_tenant_capability()
    seeded = await capability.create(
        TENANT_B_CTX,
        AppointmentCreateRequest(
            slot_id="slot-b-1",
            booking_token=SecretStr("tok-b-secret"),
            patient=PatientRef(name=CANARY_B_PATIENT, email="bravo@example.com"),
        ),
        idempotency_key="seed-b",
    )
    assert seeded.ok
    repository = InMemoryWorkflowRepository()
    definition = CancelAppointmentDefinition()
    engine = WorkflowEngine(repository, definition)
    executor = ToolExecutor(
        server=ALL_TOOLS,
        tenant=ALL_TOOLS,
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
    assert CANARY_B_PRACTITIONER not in blob
    assert CANARY_B_LOCATION not in blob
    assert CANARY_B_PATIENT not in blob
    assert "traceback" not in blob.lower()
    current = await capability.get(
        TENANT_B_CTX, AppointmentGetRequest(appointment_id="appt-b-1")
    )
    assert current.ok
    assert current.value is not None
    assert current.value.status is AppointmentStatus.SCHEDULED
