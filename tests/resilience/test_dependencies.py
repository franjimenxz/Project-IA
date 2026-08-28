from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest
from pydantic import SecretStr

from ia_mcp.agent_runtime.models import LLMDecision
from ia_mcp.configuration.models import AgentConfig, AppointmentPolicy, TenantConfig
from ia_mcp.contracts.appointments import AppointmentSlot
from ia_mcp.conversation.models import Conversation, InboundMessage
from ia_mcp.handoff.adapters.fake import FakeHandoffAdapter
from ia_mcp.handoff.models import HandoffRequest
from ia_mcp.handoff.service import HandoffService
from ia_mcp.knowledge.models import KnowledgeHit
from ia_mcp.mcp.executor import ToolExecutor
from ia_mcp.mcp.fakes.appointments import FakeAppointmentCapability
from ia_mcp.scheduling.models import AppointmentScheduledEvent, SchedulingPolicy
from ia_mcp.scheduling.service import ReminderScheduler
from ia_mcp.scheduling.worker import JobWorker
from ia_mcp.tenancy.models import TenantContext
from ia_mcp.workflows.appointments.create import CreateAppointmentDefinition
from ia_mcp.workflows.engine import WorkflowEngine
from ia_mcp.workflows.models import AdvanceCommand, StartWorkflow
from ia_mcp.workflows.ports import WorkflowError
from tests.fixtures.faults import (
    InjectedFault,
    instrument_channel,
    instrument_handoff_provider,
    instrument_handoff_repository,
    instrument_kb,
    instrument_llm,
    instrument_mcp,
    instrument_redis_repository,
    instrument_workflow_repository,
    make_faq_harness,
    new_controller,
    silent_controller,
)
from tests.unit.handoff.fakes import InMemoryHandoffRepository
from tests.unit.scheduling.fakes import (
    AdjustableClock,
    FakeAppointmentLookup,
    FakeChannelAdapter,
    InMemoryAuditSink,
    InMemoryJobStore,
)
from tests.unit.workflows.fakes import InMemoryWorkflowRepository

pytestmark = [pytest.mark.anyio, pytest.mark.resilience]

TENANT_A = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
TENANT_A_CTX = TenantContext(
    tenant_id=TENANT_A,
    tenant_slug="tenant-a",
    config_version=1,
    correlation_id=UUID("33333333-3333-3333-3333-333333333333"),
)
CLOCK = datetime(2026, 9, 1, 12, tzinfo=UTC)
BA = ZoneInfo("America/Argentina/Buenos_Aires")
STARTS_AT = datetime(2026, 9, 3, 12, 0, tzinfo=BA)
DUE_AT = datetime(2026, 9, 1, 12, 0, tzinfo=BA)
CHANNEL_A = UUID("aa111111-1111-1111-1111-111111111111")
ALL_TOOLS = frozenset(
    {
        "appointments.search",
        "appointments.get",
        "appointments.create",
        "appointments.cancel",
        "appointments.reschedule",
        "appointments.confirm",
    }
)
SEARCH_AND_CREATE = frozenset({"appointments.search", "appointments.create"})
FIELDS_A = ("specialty", "date_from", "date_to")
VALID_A: dict[str, object] = {
    "specialty": "cardiologia",
    "date_from": "2026-09-01",
    "date_to": "2026-09-01",
}
PATIENT = {"name": "Ada Lovelace", "email": "ada@example.com"}
DOC_A = UUID("aaaaaaaa-0000-4000-8000-000000000001")


def _config() -> TenantConfig:
    return TenantConfig(
        tenant_id=TENANT_A,
        version=1,
        agent=AgentConfig(tone="cordial"),
        enabled_skills=frozenset({"appointments"}),
        appointments=AppointmentPolicy(required_fields=FIELDS_A),
    )


def _slot() -> AppointmentSlot:
    return AppointmentSlot(
        slot_id="slot-a-1",
        starts_at=datetime(2026, 9, 1, 13, 0, tzinfo=UTC),
        ends_at=datetime(2026, 9, 1, 13, 30, tzinfo=UTC),
        specialty="cardiologia",
        practitioner="Dr. Ada",
        location="sede-centro",
        booking_token=SecretStr("tok-a-secret"),
    )


def _capability() -> FakeAppointmentCapability:
    return FakeAppointmentCapability(
        clock=lambda: CLOCK, initial_slots={TENANT_A: (_slot(),)}
    )


def _executor(capability: FakeAppointmentCapability) -> ToolExecutor:
    return ToolExecutor(
        server=ALL_TOOLS,
        tenant=ALL_TOOLS,
        skill=SEARCH_AND_CREATE,
        capability=capability,
    )


async def _prepare_create(
    engine: WorkflowEngine,
    definition: CreateAppointmentDefinition,
    executor: ToolExecutor,
) -> UUID:
    config = _config()
    started = await definition.start(
        engine, TENANT_A_CTX, command_id="start-1", config=config
    )
    await definition.collect_fields(
        engine,
        TENANT_A_CTX,
        started.workflow_id,
        command_id="collect-1",
        fields=VALID_A,
        config=config,
    )
    await definition.search_slots(
        engine,
        executor,
        TENANT_A_CTX,
        started.workflow_id,
        command_id="search-1",
        run_id=uuid4(),
        config=config,
    )
    await definition.select_slot(
        engine,
        TENANT_A_CTX,
        started.workflow_id,
        command_id="select-1",
        slot_id="slot-a-1",
    )
    return started.workflow_id


def _appointment_count(capability: FakeAppointmentCapability) -> int:
    agenda = capability._agendas.get(TENANT_A)
    if agenda is None:
        return 0
    return len(agenda.appointments)


async def test_mcp_timeout_before_create_does_not_mutate() -> None:
    repository = InMemoryWorkflowRepository()
    definition = CreateAppointmentDefinition()
    engine = WorkflowEngine(repository, definition)
    capability = _capability()
    controller = new_controller(
        InjectedFault(dependency="mcp", boundary="before", kind="timeout")
    )
    instrumented = instrument_mcp(capability, controller)
    executor = _executor(instrumented)
    workflow_id = await _prepare_create(engine, definition, executor)
    before = _appointment_count(capability)
    result = await definition.confirm_create(
        engine,
        executor,
        TENANT_A_CTX,
        workflow_id,
        command_id="confirm-1",
        run_id=uuid4(),
        config=_config(),
        patient=PATIENT,
    )
    assert result.state == "manual_review_required"
    assert _appointment_count(capability) == before == 0
    assert controller.side_effect_count("mcp.create") == 0


async def test_mcp_timeout_after_create_requires_manual_review_without_duplicate() -> None:
    repository = InMemoryWorkflowRepository()
    definition = CreateAppointmentDefinition()
    engine = WorkflowEngine(repository, definition)
    capability = _capability()
    controller = new_controller(
        InjectedFault(dependency="mcp", boundary="after", kind="timeout")
    )
    instrumented = instrument_mcp(capability, controller)
    executor = _executor(instrumented)
    workflow_id = await _prepare_create(engine, definition, executor)
    result = await definition.confirm_create(
        engine,
        executor,
        TENANT_A_CTX,
        workflow_id,
        command_id="confirm-1",
        run_id=uuid4(),
        config=_config(),
        patient=PATIENT,
    )
    assert result.state == "manual_review_required"
    assert _appointment_count(capability) == 1
    assert controller.side_effect_count("mcp.create") == 1
    replay = await definition.confirm_create(
        engine,
        executor,
        TENANT_A_CTX,
        workflow_id,
        command_id="confirm-1",
        run_id=uuid4(),
        config=_config(),
        patient=PATIENT,
    )
    assert replay.state == "manual_review_required"
    assert _appointment_count(capability) == 1


async def test_db_fault_before_cas_then_recovers_without_duplicate() -> None:
    inner = InMemoryWorkflowRepository()
    controller = new_controller(
        InjectedFault(dependency="db", boundary="before", kind="unavailable")
    )
    repository = instrument_workflow_repository(inner, controller)
    engine = WorkflowEngine(repository, CreateAppointmentDefinition())
    started = await engine.start(
        TENANT_A_CTX,
        StartWorkflow(command_id="start-1", workflow_type="generic", schema_version=1),
    )
    with pytest.raises(WorkflowError) as caught:
        await engine.advance(
            TENANT_A_CTX,
            AdvanceCommand(
                workflow_id=started.workflow_id,
                command_id="cmd-1",
                event_type="submit",
            ),
        )
    assert caught.value.code == "upstream_unavailable"
    assert controller.side_effect_count("db.cas_advance") == 0
    loaded = await inner.get(TENANT_A_CTX, started.workflow_id)
    assert loaded is not None
    assert loaded.state == "collecting"
    recovered = await engine.advance(
        TENANT_A_CTX,
        AdvanceCommand(
            workflow_id=started.workflow_id,
            command_id="cmd-1",
            event_type="submit",
        ),
    )
    assert recovered.state == "awaiting_confirmation"
    assert (
        await inner.count_transitions(
            TENANT_A_CTX, started.workflow_id, command_id="cmd-1"
        )
        == 1
    )


async def test_db_fault_after_cas_recovers_from_durable_state() -> None:
    inner = InMemoryWorkflowRepository()
    controller = new_controller(
        InjectedFault(dependency="db", boundary="after", kind="unavailable")
    )
    repository = instrument_workflow_repository(inner, controller)
    engine = WorkflowEngine(repository, CreateAppointmentDefinition())
    started = await engine.start(
        TENANT_A_CTX,
        StartWorkflow(command_id="start-1", workflow_type="generic", schema_version=1),
    )
    with pytest.raises(WorkflowError) as caught:
        await engine.advance(
            TENANT_A_CTX,
            AdvanceCommand(
                workflow_id=started.workflow_id,
                command_id="cmd-1",
                event_type="submit",
            ),
        )
    assert caught.value.code == "upstream_unavailable"
    assert controller.side_effect_count("db.cas_advance") == 1
    durable = await inner.get(TENANT_A_CTX, started.workflow_id)
    assert durable is not None
    assert durable.state == "awaiting_confirmation"
    recovered = await engine.advance(
        TENANT_A_CTX,
        AdvanceCommand(
            workflow_id=started.workflow_id,
            command_id="cmd-1",
            event_type="submit",
        ),
    )
    assert recovered.state == "awaiting_confirmation"
    assert (
        await inner.count_transitions(
            TENANT_A_CTX, started.workflow_id, command_id="cmd-1"
        )
        == 1
    )


async def test_redis_fault_before_cache_write_keeps_durable_state() -> None:
    inner = InMemoryWorkflowRepository()
    controller = new_controller(
        InjectedFault(dependency="redis", boundary="before", kind="unavailable")
    )
    repository = instrument_redis_repository(inner, controller)
    engine = WorkflowEngine(repository, CreateAppointmentDefinition())
    started = await engine.start(
        TENANT_A_CTX,
        StartWorkflow(command_id="start-1", workflow_type="generic", schema_version=1),
    )
    advanced = await engine.advance(
        TENANT_A_CTX,
        AdvanceCommand(
            workflow_id=started.workflow_id,
            command_id="cmd-1",
            event_type="submit",
        ),
    )
    assert advanced.state == "awaiting_confirmation"
    assert controller.side_effect_count("redis.set") == 0
    loaded = await inner.get(TENANT_A_CTX, started.workflow_id)
    assert loaded is not None
    assert loaded.state == "awaiting_confirmation"


async def test_redis_fault_after_cache_write_recovers_without_duplicate() -> None:
    inner = InMemoryWorkflowRepository()
    controller = new_controller(
        InjectedFault(dependency="redis", boundary="after", kind="unavailable")
    )
    repository = instrument_redis_repository(inner, controller)
    engine = WorkflowEngine(repository, CreateAppointmentDefinition())
    started = await engine.start(
        TENANT_A_CTX,
        StartWorkflow(command_id="start-1", workflow_type="generic", schema_version=1),
    )
    with pytest.raises(WorkflowError) as caught:
        await engine.advance(
            TENANT_A_CTX,
            AdvanceCommand(
                workflow_id=started.workflow_id,
                command_id="cmd-1",
                event_type="submit",
            ),
        )
    assert caught.value.code == "upstream_unavailable"
    assert controller.side_effect_count("redis.set") == 1
    durable = await inner.get(TENANT_A_CTX, started.workflow_id)
    assert durable is not None
    assert durable.state == "awaiting_confirmation"
    recovered = await engine.advance(
        TENANT_A_CTX,
        AdvanceCommand(
            workflow_id=started.workflow_id,
            command_id="cmd-1",
            event_type="submit",
        ),
    )
    assert recovered.state == "awaiting_confirmation"
    assert (
        await inner.count_transitions(
            TENANT_A_CTX, started.workflow_id, command_id="cmd-1"
        )
        == 1
    )


async def test_llm_fault_before_generate_does_not_invent_facts() -> None:
    controller = new_controller(
        InjectedFault(dependency="llm", boundary="before", kind="unavailable")
    )
    llm = instrument_llm(
        LLMDecision(kind="answer", text="Hours are 8 to 16.", source_ids=("src-a",)),
        controller,
    )
    kb = instrument_kb((_hit(),), silent_controller())
    harness, runs = make_faq_harness(knowledge=kb, llm=llm)
    result = await harness.handle_message(
        TENANT_A_CTX,
        InboundMessage(
            channel="simulated",
            channel_account_id="acct-a",
            channel_integration_id=CHANNEL_A,
            external_message_id="m-1",
            external_user_id="user-a",
            text="hours",
            occurred_at=CLOCK,
        ),
    )
    assert result.kind == "insufficient"
    assert "8 to 16" not in result.text
    assert controller.side_effect_count("llm.generate") == 0
    assert runs.finished and runs.finished[0][1] == "failed"


async def test_llm_fault_after_generate_does_not_invent_facts() -> None:
    controller = new_controller(
        InjectedFault(dependency="llm", boundary="after", kind="unavailable")
    )
    llm = instrument_llm(
        LLMDecision(kind="answer", text="Hours are 8 to 16.", source_ids=("src-a",)),
        controller,
    )
    kb = instrument_kb((_hit(),), silent_controller())
    harness, runs = make_faq_harness(knowledge=kb, llm=llm)
    result = await harness.handle_message(
        TENANT_A_CTX,
        InboundMessage(
            channel="simulated",
            channel_account_id="acct-a",
            channel_integration_id=CHANNEL_A,
            external_message_id="m-2",
            external_user_id="user-a",
            text="hours",
            occurred_at=CLOCK,
        ),
    )
    assert result.kind == "insufficient"
    assert "8 to 16" not in result.text
    assert controller.side_effect_count("llm.generate") == 1
    assert runs.finished and runs.finished[0][1] == "failed"


async def test_kb_fault_before_search_does_not_invent_facts() -> None:
    controller = new_controller(
        InjectedFault(dependency="kb", boundary="before", kind="unavailable")
    )
    kb = instrument_kb((_hit(),), controller)
    llm = instrument_llm(
        LLMDecision(kind="answer", text="Hours are 8 to 16.", source_ids=("src-a",)),
        silent_controller(),
    )
    harness, _runs = make_faq_harness(knowledge=kb, llm=llm)
    result = await harness.handle_message(
        TENANT_A_CTX,
        InboundMessage(
            channel="simulated",
            channel_account_id="acct-a",
            channel_integration_id=CHANNEL_A,
            external_message_id="m-3",
            external_user_id="user-a",
            text="hours",
            occurred_at=CLOCK,
        ),
    )
    assert result.kind == "insufficient"
    assert controller.side_effect_count("kb.search") == 0
    assert llm.requests == []


async def test_kb_fault_after_search_does_not_invent_facts() -> None:
    controller = new_controller(
        InjectedFault(dependency="kb", boundary="after", kind="unavailable")
    )
    kb = instrument_kb((_hit(),), controller)
    llm = instrument_llm(
        LLMDecision(kind="answer", text="Hours are 8 to 16.", source_ids=("src-a",)),
        silent_controller(),
    )
    harness, _runs = make_faq_harness(knowledge=kb, llm=llm)
    result = await harness.handle_message(
        TENANT_A_CTX,
        InboundMessage(
            channel="simulated",
            channel_account_id="acct-a",
            channel_integration_id=CHANNEL_A,
            external_message_id="m-4",
            external_user_id="user-a",
            text="hours",
            occurred_at=CLOCK,
        ),
    )
    assert result.kind == "insufficient"
    assert controller.side_effect_count("kb.search") == 1
    assert llm.requests == []


async def test_channel_fault_before_send_retries_then_delivers_once() -> None:
    store = InMemoryJobStore()
    clock = AdjustableClock(DUE_AT)
    policy = SchedulingPolicy(max_attempts=3)
    controller = new_controller(
        InjectedFault(
            dependency="channel", boundary="before", kind="unavailable", times=1
        )
    )
    channel = instrument_channel(FakeChannelAdapter(), controller)
    lookup = FakeAppointmentLookup()
    lookup.set_status(TENANT_A, "appt-1", "scheduled")
    scheduler = ReminderScheduler(store=store, clock=clock, policy=policy)
    worker = JobWorker(
        store=store,
        clock=clock,
        channel=channel,
        lookup=lookup,
        policy=policy,
        audit=InMemoryAuditSink(),
        owner="worker-1",
    )
    await scheduler.upsert(
        TENANT_A_CTX,
        AppointmentScheduledEvent(appointment_id="appt-1", starts_at=STARTS_AT),
    )
    first = await worker.dispatch(await _require_claim(worker))
    assert first.status == "retry"
    assert controller.side_effect_count("channel.send") == 0
    second = await worker.dispatch(await _require_claim(worker))
    assert second.status == "dispatched"
    assert len(channel.deliveries_for(TENANT_A_CTX)) == 1
    assert controller.side_effect_count("channel.send") == 1


async def test_channel_fault_after_send_retries_without_duplicate_delivery() -> None:
    store = InMemoryJobStore()
    clock = AdjustableClock(DUE_AT)
    policy = SchedulingPolicy(max_attempts=3)
    controller = new_controller(
        InjectedFault(
            dependency="channel", boundary="after", kind="unavailable", times=1
        )
    )
    channel = instrument_channel(FakeChannelAdapter(), controller)
    lookup = FakeAppointmentLookup()
    lookup.set_status(TENANT_A, "appt-1", "scheduled")
    scheduler = ReminderScheduler(store=store, clock=clock, policy=policy)
    worker = JobWorker(
        store=store,
        clock=clock,
        channel=channel,
        lookup=lookup,
        policy=policy,
        audit=InMemoryAuditSink(),
        owner="worker-1",
    )
    await scheduler.upsert(
        TENANT_A_CTX,
        AppointmentScheduledEvent(appointment_id="appt-1", starts_at=STARTS_AT),
    )
    first = await worker.dispatch(await _require_claim(worker))
    assert first.status == "retry"
    assert controller.side_effect_count("channel.send") == 1
    second = await worker.dispatch(await _require_claim(worker))
    assert second.status == "dispatched"
    assert len(channel.deliveries_for(TENANT_A_CTX)) == 1


async def test_handoff_fault_before_persist_then_recovers_once() -> None:
    inner = InMemoryHandoffRepository()
    conversation = _conversation()
    inner.seed_conversation(conversation)
    controller = new_controller(
        InjectedFault(dependency="handoff", boundary="before", kind="unavailable")
    )
    repository = instrument_handoff_repository(inner, controller)
    service = HandoffService(repository, FakeHandoffAdapter())
    request = HandoffRequest(
        conversation_id=conversation.id,
        reason="explicit_request",
        business_key="handoff:conv-a",
    )
    with pytest.raises(Exception) as caught:
        await service.create(TENANT_A_CTX, request)
    assert getattr(caught.value, "code", "") == "upstream_unavailable"
    assert await inner.count_cases(TENANT_A_CTX) == 0
    recovered = await service.create(TENANT_A_CTX, request)
    assert recovered.replayed is False
    assert await inner.count_cases(TENANT_A_CTX) == 1


async def test_handoff_fault_after_transfer_replays_without_duplicate() -> None:
    inner = InMemoryHandoffRepository()
    conversation = _conversation()
    inner.seed_conversation(conversation)
    controller = new_controller(
        InjectedFault(dependency="handoff", boundary="after", kind="unavailable")
    )
    provider = instrument_handoff_provider(FakeHandoffAdapter(), controller)
    service = HandoffService(inner, provider)
    request = HandoffRequest(
        conversation_id=conversation.id,
        reason="persistent_error",
        business_key="handoff:conv-a",
    )
    first = await service.create(TENANT_A_CTX, request)
    assert first.delivery_pending is True
    assert await inner.count_cases(TENANT_A_CTX) == 1
    assert controller.side_effect_count("handoff.transfer") == 1
    replay = await service.create(TENANT_A_CTX, request)
    assert replay.replayed is True
    assert await inner.count_cases(TENANT_A_CTX) == 1
    assert controller.side_effect_count("handoff.transfer") == 1


def _hit() -> KnowledgeHit:
    return KnowledgeHit(
        tenant_id=TENANT_A,
        source_id="src-a",
        text="Hours are 8 to 16.",
        score=0.9,
        document_id=DOC_A,
        document_version=1,
        page=1,
    )


def _conversation() -> Conversation:
    return Conversation(
        id=uuid4(),
        tenant_id=TENANT_A,
        channel_integration_id=CHANNEL_A,
        status="bot_owned",
        last_message_at=datetime.now(UTC),
        lock_version=1,
    )


async def _require_claim(worker: JobWorker):
    claim = await worker.claim()
    assert claim is not None
    return claim
