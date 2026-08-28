from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from alembic.config import Config
from pydantic import SecretStr
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import AsyncEngine

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
from ia_mcp.configuration.models import AgentConfig, AppointmentPolicy, TenantConfig
from ia_mcp.contracts.appointments import AppointmentGetRequest, AppointmentSlot
from ia_mcp.conversation.adapters.sqlalchemy import SqlAlchemyConversationRepository
from ia_mcp.conversation.models import InboundMessage, ReceivedMessage
from ia_mcp.handoff.adapters.fake import FakeHandoffAdapter
from ia_mcp.handoff.service import HandoffService, SqlAlchemyHandoffRepository
from ia_mcp.knowledge.models import KnowledgeHit, KnowledgeQuery
from ia_mcp.mcp.executor import ToolExecutor
from ia_mcp.mcp.fakes.appointments import FakeAppointmentCapability, FaultPlan
from ia_mcp.scheduling.models import SchedulingPolicy
from ia_mcp.scheduling.service import ReminderScheduler, SqlAlchemyJobStore
from ia_mcp.skills.registry import SkillRegistry
from ia_mcp.tenancy.models import TenantContext
from ia_mcp.workflows.adapters.sqlalchemy import SqlAlchemyWorkflowRepository
from ia_mcp.workflows.appointments.cancel import CancelAppointmentDefinition
from ia_mcp.workflows.appointments.create import CreateAppointmentDefinition
from ia_mcp.workflows.appointments.reschedule import RescheduleAppointmentDefinition
from ia_mcp.workflows.engine import WorkflowEngine
from ia_mcp.workflows.models import WorkflowResult
from ia_mcp.workflows.ports import WorkflowDefinition
from tests.unit.scheduling.fakes import (
    AdjustableClock,
    FakeChannelAdapter,
    InMemoryAuditSink,
)

ROOT = Path(__file__).resolve().parents[2]
DATABASE_URL = "postgresql+psycopg://francojimenez@127.0.0.1:5432/ia_mcp_p02_t03"

TENANT_A = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
TENANT_B = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
CHANNEL_A = UUID("aa111111-1111-1111-1111-111111111111")
CHANNEL_B = UUID("bb111111-1111-1111-1111-111111111111")
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

BA = ZoneInfo("America/Argentina/Buenos_Aires")
CAPABILITY_CLOCK = datetime(2026, 8, 28, 12, 0, tzinfo=BA)
STARTS_AT = datetime(2026, 9, 3, 12, 0, tzinfo=BA)
ENDS_AT = datetime(2026, 9, 3, 12, 30, tzinfo=BA)
STARTS_RESCHEDULED = datetime(2026, 9, 4, 12, 0, tzinfo=BA)
ENDS_RESCHEDULED = datetime(2026, 9, 4, 12, 30, tzinfo=BA)
DUE_AT = datetime(2026, 9, 1, 12, 0, tzinfo=BA)
DUE_RESCHEDULED = datetime(2026, 9, 2, 12, 0, tzinfo=BA)
OCCURRED_AT = datetime(2026, 8, 28, 5, 0, tzinfo=UTC)

FIELDS_A = ("specialty", "date_from", "date_to")
VALID_A: dict[str, object] = {
    "specialty": "cardiologia",
    "date_from": "2026-09-03",
    "date_to": "2026-09-04",
}
PATIENT: dict[str, object] = {"name": "Ada Lovelace", "email": "ada@example.com"}
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
CONFIRM_TOOLS = frozenset({"appointments.get", "appointments.confirm"})


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


class CountingCapability(FakeAppointmentCapability):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.operations: list[str] = []

    async def get(self, tenant: TenantContext, request: Any):
        self.operations.append("get")
        return await super().get(tenant, request)

    async def create(self, tenant: TenantContext, request: Any, idempotency_key: str):
        self.operations.append("create")
        return await super().create(tenant, request, idempotency_key)

    async def cancel(self, tenant: TenantContext, request: Any, idempotency_key: str):
        self.operations.append("cancel")
        return await super().cancel(tenant, request, idempotency_key)

    async def reschedule(
        self, tenant: TenantContext, request: Any, idempotency_key: str
    ):
        self.operations.append("reschedule")
        return await super().reschedule(tenant, request, idempotency_key)

    async def confirm(self, tenant: TenantContext, request: Any, idempotency_key: str):
        self.operations.append("confirm")
        return await super().confirm(tenant, request, idempotency_key)


class CapabilityAppointmentLookup:
    def __init__(self, capability: FakeAppointmentCapability) -> None:
        self._capability = capability

    async def status(self, tenant: TenantContext, appointment_id: str) -> str | None:
        result = await self._capability.get(
            tenant, AppointmentGetRequest(appointment_id=appointment_id)
        )
        if not result.ok or result.value is None:
            return None
        return str(result.value.status)


def parse_starts_at(value: object) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value)
    raise TypeError("starts_at must be datetime or ISO string")


def appointment_config(tenant_id: UUID) -> TenantConfig:
    return TenantConfig(
        tenant_id=tenant_id,
        version=1,
        agent=AgentConfig(tone="cordial"),
        enabled_skills=frozenset({"appointments"}),
        appointments=AppointmentPolicy(required_fields=FIELDS_A),
    )


def _slot(
    slot_id: str, starts_at: datetime, ends_at: datetime, token: str
) -> AppointmentSlot:
    return AppointmentSlot(
        slot_id=slot_id,
        starts_at=starts_at,
        ends_at=ends_at,
        specialty="cardiologia",
        practitioner="Dr. Ada",
        location="sede-centro",
        booking_token=SecretStr(token),
    )


def reset_and_seed(*, channels: bool = False) -> None:
    engine = create_engine(DATABASE_URL)
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))
    engine.dispose()
    alembic_cfg = Config(str(ROOT / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(ROOT / "alembic"))
    alembic_cfg.set_main_option("sqlalchemy.url", DATABASE_URL)
    command.upgrade(alembic_cfg, "head")
    now = datetime.now(UTC)
    tenants = [
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
    ]
    seed = create_engine(DATABASE_URL)
    with seed.begin() as connection:
        connection.execute(tenant_table.insert(), tenants)
        if channels:
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
    seed.dispose()


def make_capability(*, timeout_create: bool = False) -> CountingCapability:
    fault = (
        FaultPlan(fault="timeout", operations=frozenset({"create"}))
        if timeout_create
        else None
    )
    return CountingCapability(
        clock=lambda: CAPABILITY_CLOCK,
        initial_slots={
            TENANT_A: (
                _slot("slot-a-1", STARTS_AT, ENDS_AT, "tok-a-secret"),
                _slot("slot-a-2", STARTS_RESCHEDULED, ENDS_RESCHEDULED, "tok-a2-secret"),
            ),
            TENANT_B: (_slot("slot-b-1", STARTS_AT, ENDS_AT, "tok-b-secret"),),
        },
        fault_plan=fault,
    )


def make_executor(
    capability: FakeAppointmentCapability,
    *,
    skill: frozenset[str],
) -> ToolExecutor:
    return ToolExecutor(
        server=ALL_TOOLS,
        tenant=ALL_TOOLS,
        skill=skill,
        capability=capability,
    )


def make_workflow_engine(
    db: AsyncEngine, definition: WorkflowDefinition
) -> WorkflowEngine:
    return WorkflowEngine(SqlAlchemyWorkflowRepository(db), definition)


def make_scheduler(
    db: AsyncEngine,
    *,
    channel: FakeChannelAdapter | None = None,
    policy: SchedulingPolicy | None = None,
    clock: AdjustableClock | None = None,
) -> tuple[
    ReminderScheduler,
    SqlAlchemyJobStore,
    AdjustableClock,
    FakeChannelAdapter,
    SchedulingPolicy,
    InMemoryAuditSink,
]:
    store = SqlAlchemyJobStore(db)
    resolved_clock = clock or AdjustableClock(CAPABILITY_CLOCK)
    resolved_policy = policy or SchedulingPolicy()
    resolved_channel = channel or FakeChannelAdapter()
    audit = InMemoryAuditSink()
    scheduler = ReminderScheduler(
        store=store, clock=resolved_clock, policy=resolved_policy
    )
    return (
        scheduler,
        store,
        resolved_clock,
        resolved_channel,
        resolved_policy,
        audit,
    )


def make_handoff(
    db: AsyncEngine,
) -> tuple[
    SqlAlchemyConversationRepository,
    HandoffService,
    FakeHandoffAdapter,
    AgentHarness,
]:
    conversations = SqlAlchemyConversationRepository(db)
    provider = FakeHandoffAdapter()
    service = HandoffService(SqlAlchemyHandoffRepository(db), provider)
    configs = StaticConfigs()
    skills = SkillRegistry()
    harness = AgentHarness(
        conversations=conversations,
        runs=SqlAlchemyAgentRunRepository(db),
        configs=configs,
        skills=skills,
        compiler=ContextCompiler(
            configs=configs,
            skills=SkillRegistry(),
            tenant_tools={TENANT_A: frozenset({"appointments.create"})},
        ),
        knowledge=RecordingKnowledge(),
        llm=FakeLLM(
            LLMDecision(kind="answer", text="should not run", source_ids=("x",))
        ),
    )
    return conversations, service, provider, harness


async def open_conversation(
    conversations: SqlAlchemyConversationRepository,
    tenant: TenantContext,
    *,
    account: str,
    external_id: str,
) -> ReceivedMessage:
    channel_id = CHANNEL_A if account == "acct-a" else CHANNEL_B
    return await conversations.receive(
        tenant,
        InboundMessage(
            channel="simulated",
            channel_account_id=account,
            channel_integration_id=channel_id,
            external_message_id=external_id,
            external_user_id=f"user-{account}",
            text="help",
            occurred_at=OCCURRED_AT,
        ),
    )


async def start_create(db: AsyncEngine, tenant: TenantContext) -> WorkflowResult:
    definition = CreateAppointmentDefinition()
    engine = make_workflow_engine(db, definition)
    return await definition.start(
        engine,
        tenant,
        command_id="start-1",
        config=appointment_config(tenant.tenant_id),
    )


async def collect_and_select(
    db: AsyncEngine,
    tenant: TenantContext,
    executor: ToolExecutor,
    workflow_id: UUID,
) -> WorkflowResult:
    definition = CreateAppointmentDefinition()
    engine = make_workflow_engine(db, definition)
    config = appointment_config(tenant.tenant_id)
    await definition.collect_fields(
        engine,
        tenant,
        workflow_id,
        command_id="collect-1",
        fields=VALID_A,
        config=config,
    )
    await definition.search_slots(
        engine,
        executor,
        tenant,
        workflow_id,
        command_id="search-1",
        run_id=uuid4(),
        config=config,
    )
    return await definition.select_slot(
        engine,
        tenant,
        workflow_id,
        command_id="select-1",
        slot_id="slot-a-1",
    )


async def create_appointment(
    db: AsyncEngine, tenant: TenantContext, executor: ToolExecutor
) -> WorkflowResult:
    definition = CreateAppointmentDefinition()
    engine = make_workflow_engine(db, definition)
    started = await start_create(db, tenant)
    await collect_and_select(db, tenant, executor, started.workflow_id)
    return await definition.confirm_create(
        engine,
        executor,
        tenant,
        started.workflow_id,
        command_id="confirm-create",
        run_id=uuid4(),
        config=appointment_config(tenant.tenant_id),
        patient=PATIENT,
    )


async def timeout_create(
    db: AsyncEngine, tenant: TenantContext, executor: ToolExecutor
) -> WorkflowResult:
    return await create_appointment(db, tenant, executor)


async def reschedule_appointment(
    db: AsyncEngine,
    tenant: TenantContext,
    executor: ToolExecutor,
    appointment_id: str,
    *,
    slot_id: str,
) -> WorkflowResult:
    definition = RescheduleAppointmentDefinition()
    engine = make_workflow_engine(db, definition)
    started = await definition.start(
        engine, tenant, command_id="start-reschedule", appointment_id=appointment_id
    )
    await definition.load_appointment(
        engine,
        executor,
        tenant,
        started.workflow_id,
        command_id="load-1",
        run_id=uuid4(),
    )
    await definition.search_slots(
        engine,
        executor,
        tenant,
        started.workflow_id,
        command_id="search-1",
        run_id=uuid4(),
    )
    await definition.select_slot(
        engine,
        tenant,
        started.workflow_id,
        command_id="select-1",
        slot_id=slot_id,
    )
    return await definition.confirm_reschedule(
        engine,
        executor,
        tenant,
        started.workflow_id,
        command_id="confirm-reschedule",
        run_id=uuid4(),
    )


async def cancel_with_replay(
    db: AsyncEngine,
    tenant: TenantContext,
    executor: ToolExecutor,
    appointment_id: str,
    *,
    command_id: str,
) -> tuple[WorkflowResult, WorkflowResult]:
    definition = CancelAppointmentDefinition()
    engine = make_workflow_engine(db, definition)
    config = appointment_config(tenant.tenant_id)
    started = await definition.start(
        engine,
        tenant,
        command_id="start-cancel",
        config=config,
        appointment_id=appointment_id,
    )
    await definition.lookup(
        engine,
        executor,
        tenant,
        started.workflow_id,
        command_id="lookup-1",
        run_id=uuid4(),
        config=config,
    )
    run_id = uuid4()
    first = await definition.confirm_cancel(
        engine,
        executor,
        tenant,
        started.workflow_id,
        command_id=command_id,
        run_id=run_id,
        config=config,
        confirmed=True,
    )
    replay = await definition.confirm_cancel(
        engine,
        executor,
        tenant,
        started.workflow_id,
        command_id=command_id,
        run_id=run_id,
        config=config,
        confirmed=True,
    )
    return first, replay
