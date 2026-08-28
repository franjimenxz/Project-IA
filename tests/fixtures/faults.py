"""Deterministic fault injection for resilience tests. No network or real sleeps."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from ia_mcp.agent_runtime.context_compiler import ContextCompiler
from ia_mcp.agent_runtime.harness import AgentHarness
from ia_mcp.agent_runtime.models import LLMDecision, LLMRequest
from ia_mcp.agent_runtime.ports import LLMError
from ia_mcp.agent_runtime.run_repository import AgentRun, AgentRunResult
from ia_mcp.configuration.models import AgentConfig, TenantConfig
from ia_mcp.contracts.appointments import (
    Appointment,
    AppointmentCancelRequest,
    AppointmentConfirmRequest,
    AppointmentCreateRequest,
    AppointmentGetRequest,
    AppointmentRescheduleRequest,
    AppointmentSearchRequest,
    AppointmentSlot,
)
from ia_mcp.contracts.common import ToolResult
from ia_mcp.contracts.errors import ToolError
from ia_mcp.conversation.models import (
    Conversation,
    InboundMessage,
    Message,
    ReceivedMessage,
    SessionState,
)
from ia_mcp.handoff.adapters.fake import FakeHandoffAdapter
from ia_mcp.handoff.models import HandoffCase, HandoffDelivery, HandoffOutbox
from ia_mcp.handoff.ports import HandoffError
from ia_mcp.knowledge.models import KnowledgeHit, KnowledgeQuery
from ia_mcp.knowledge.ports import KnowledgeError
from ia_mcp.mcp.fakes.appointments import FakeAppointmentCapability, FaultPlan
from ia_mcp.scheduling.models import DeliveryResult, OutboundReminder
from ia_mcp.skills.registry import SkillRegistry
from ia_mcp.tenancy.models import TenantContext
from ia_mcp.workflows.models import OutboxEvent, WorkflowExecution, WorkflowTransition
from ia_mcp.workflows.ports import WorkflowError
from tests.unit.handoff.fakes import InMemoryHandoffRepository
from tests.unit.scheduling.fakes import FakeChannelAdapter
from tests.unit.workflows.fakes import InMemoryWorkflowRepository

type DependencyName = Literal[
    "db", "redis", "llm", "kb", "mcp", "channel", "handoff"
]
type FaultBoundary = Literal["before", "after"]
type FaultKind = Literal["timeout", "unavailable", "malformed"]

_TENANT_A = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")


@dataclass(frozen=True, slots=True)
class InjectedFault:
    dependency: DependencyName
    boundary: FaultBoundary = "before"
    kind: FaultKind = "unavailable"
    times: int = 1
    operations: frozenset[str] | None = None


@dataclass(slots=True)
class FaultController:
    plan: InjectedFault
    side_effects: list[str] = field(default_factory=list)
    attempts: list[str] = field(default_factory=list)
    _remaining: int = field(init=False)

    def __post_init__(self) -> None:
        self._remaining = self.plan.times

    def consume(self, dependency: str, operation: str, boundary: str) -> bool:
        if self.plan.dependency != dependency:
            return False
        if self.plan.boundary != boundary:
            return False
        if (
            self.plan.operations is not None
            and operation not in self.plan.operations
        ):
            return False
        if self._remaining <= 0:
            return False
        self._remaining -= 1
        return True

    def record(self, name: str) -> None:
        self.side_effects.append(name)

    def side_effect_count(self, name: str) -> int:
        return self.side_effects.count(name)


def new_controller(plan: InjectedFault) -> FaultController:
    return FaultController(plan=plan)


def silent_controller() -> FaultController:
    return new_controller(InjectedFault(dependency="db", times=0))


def _mcp_error(kind: FaultKind, operation: str) -> ToolError:
    fault: Literal["timeout", "rate_limit", "malformed"]
    if kind == "malformed":
        fault = "malformed"
    elif kind == "unavailable":
        fault = "rate_limit"
    else:
        fault = "timeout"
    plan = FaultPlan(fault=fault, operations=frozenset({operation}))
    error = FakeAppointmentCapability(fault_plan=plan)._fault(operation)
    if error is None:
        raise RuntimeError("fault-plan port did not produce an error")
    return error


def _fail_appointment(error: ToolError) -> ToolResult[Appointment]:
    return ToolResult[Appointment](ok=False, error=error)


class InstrumentedCapability:
    def __init__(
        self, inner: FakeAppointmentCapability, controller: FaultController
    ) -> None:
        self._inner = inner
        self._controller = controller

    async def search(
        self, tenant: TenantContext, request: AppointmentSearchRequest
    ) -> ToolResult[list[AppointmentSlot]]:
        return await self._inner.search(tenant, request)

    async def get(
        self, tenant: TenantContext, request: AppointmentGetRequest
    ) -> ToolResult[Appointment]:
        return await self._inner.get(tenant, request)

    async def create(
        self,
        tenant: TenantContext,
        request: AppointmentCreateRequest,
        idempotency_key: str,
    ) -> ToolResult[Appointment]:
        return await self._mutate("create", tenant, request, idempotency_key)

    async def cancel(
        self,
        tenant: TenantContext,
        request: AppointmentCancelRequest,
        idempotency_key: str,
    ) -> ToolResult[Appointment]:
        return await self._mutate("cancel", tenant, request, idempotency_key)

    async def reschedule(
        self,
        tenant: TenantContext,
        request: AppointmentRescheduleRequest,
        idempotency_key: str,
    ) -> ToolResult[Appointment]:
        return await self._mutate("reschedule", tenant, request, idempotency_key)

    async def confirm(
        self,
        tenant: TenantContext,
        request: AppointmentConfirmRequest,
        idempotency_key: str,
    ) -> ToolResult[Appointment]:
        return await self._mutate("confirm", tenant, request, idempotency_key)

    async def _mutate(
        self,
        operation: str,
        tenant: TenantContext,
        request: Any,
        idempotency_key: str,
    ) -> ToolResult[Appointment]:
        self._controller.attempts.append(f"mcp.{operation}")
        if self._controller.consume("mcp", operation, "before"):
            return _fail_appointment(
                _mcp_error(self._controller.plan.kind, operation)
            )
        method = getattr(self._inner, operation)
        result = await method(tenant, request, idempotency_key)
        if result.ok:
            self._controller.record(f"mcp.{operation}")
            if self._controller.consume("mcp", operation, "after"):
                return _fail_appointment(
                    _mcp_error(self._controller.plan.kind, operation)
                )
        return result


def instrument_mcp(
    capability: FakeAppointmentCapability, controller: FaultController
) -> InstrumentedCapability:
    return InstrumentedCapability(capability, controller)


class InstrumentedWorkflowRepository:
    def __init__(
        self, inner: InMemoryWorkflowRepository, controller: FaultController
    ) -> None:
        self._inner = inner
        self._controller = controller

    async def create(
        self,
        tenant: TenantContext,
        execution: WorkflowExecution,
        transition: WorkflowTransition,
        outbox: OutboxEvent,
    ) -> None:
        await self._inner.create(tenant, execution, transition, outbox)

    async def get(
        self, tenant: TenantContext, workflow_id: UUID
    ) -> WorkflowExecution | None:
        return await self._inner.get(tenant, workflow_id)

    async def get_by_idempotency(
        self, tenant: TenantContext, idempotency_key_hash: str
    ) -> WorkflowExecution | None:
        return await self._inner.get_by_idempotency(tenant, idempotency_key_hash)

    async def get_transition(
        self, tenant: TenantContext, workflow_id: UUID, command_id: str
    ) -> WorkflowTransition | None:
        return await self._inner.get_transition(tenant, workflow_id, command_id)

    async def list_transitions(
        self, tenant: TenantContext, workflow_id: UUID
    ) -> tuple[WorkflowTransition, ...]:
        return await self._inner.list_transitions(tenant, workflow_id)

    async def count_transitions(
        self,
        tenant: TenantContext,
        workflow_id: UUID,
        *,
        command_id: str | None = None,
    ) -> int:
        return await self._inner.count_transitions(
            tenant, workflow_id, command_id=command_id
        )

    async def cas_advance(
        self,
        tenant: TenantContext,
        expected_lock_version: int,
        execution: WorkflowExecution,
        transition: WorkflowTransition,
        outbox: OutboxEvent,
    ) -> WorkflowExecution:
        if self._controller.consume("db", "cas_advance", "before"):
            raise WorkflowError(
                "upstream_unavailable", "Database is unavailable."
            )
        stored = await self._inner.cas_advance(
            tenant, expected_lock_version, execution, transition, outbox
        )
        self._controller.record("db.cas_advance")
        if self._controller.consume("db", "cas_advance", "after"):
            raise WorkflowError(
                "upstream_unavailable", "Database is unavailable."
            )
        return stored


def instrument_workflow_repository(
    inner: InMemoryWorkflowRepository, controller: FaultController
) -> InstrumentedWorkflowRepository:
    return InstrumentedWorkflowRepository(inner, controller)


class FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, object] = {}

    def set(self, key: str, value: object) -> None:
        self.store[key] = value

    def get(self, key: str) -> object | None:
        return self.store.get(key)


class RedisCoordinatedRepository:
    """Durable store is authoritative; Redis is cache-only (system TDD §17)."""

    def __init__(
        self, inner: InMemoryWorkflowRepository, controller: FaultController
    ) -> None:
        self._inner = inner
        self._controller = controller
        self._redis = FakeRedis()

    async def create(
        self,
        tenant: TenantContext,
        execution: WorkflowExecution,
        transition: WorkflowTransition,
        outbox: OutboxEvent,
    ) -> None:
        await self._inner.create(tenant, execution, transition, outbox)

    async def get(
        self, tenant: TenantContext, workflow_id: UUID
    ) -> WorkflowExecution | None:
        return await self._inner.get(tenant, workflow_id)

    async def get_by_idempotency(
        self, tenant: TenantContext, idempotency_key_hash: str
    ) -> WorkflowExecution | None:
        return await self._inner.get_by_idempotency(tenant, idempotency_key_hash)

    async def get_transition(
        self, tenant: TenantContext, workflow_id: UUID, command_id: str
    ) -> WorkflowTransition | None:
        return await self._inner.get_transition(tenant, workflow_id, command_id)

    async def list_transitions(
        self, tenant: TenantContext, workflow_id: UUID
    ) -> tuple[WorkflowTransition, ...]:
        return await self._inner.list_transitions(tenant, workflow_id)

    async def count_transitions(
        self,
        tenant: TenantContext,
        workflow_id: UUID,
        *,
        command_id: str | None = None,
    ) -> int:
        return await self._inner.count_transitions(
            tenant, workflow_id, command_id=command_id
        )

    async def cas_advance(
        self,
        tenant: TenantContext,
        expected_lock_version: int,
        execution: WorkflowExecution,
        transition: WorkflowTransition,
        outbox: OutboxEvent,
    ) -> WorkflowExecution:
        skip_cache = self._controller.consume("redis", "cas_advance", "before")
        stored = await self._inner.cas_advance(
            tenant, expected_lock_version, execution, transition, outbox
        )
        if skip_cache:
            return stored
        key = f"{tenant.tenant_id}:{execution.id}"
        self._redis.set(key, stored)
        self._controller.record("redis.set")
        if self._controller.consume("redis", "cas_advance", "after"):
            raise WorkflowError("upstream_unavailable", "Redis is unavailable.")
        return stored


def instrument_redis_repository(
    inner: InMemoryWorkflowRepository, controller: FaultController
) -> RedisCoordinatedRepository:
    return RedisCoordinatedRepository(inner, controller)


class InstrumentedChannel:
    def __init__(
        self, inner: FakeChannelAdapter, controller: FaultController
    ) -> None:
        self._inner = inner
        self._controller = controller

    async def send(
        self, tenant: TenantContext, message: OutboundReminder
    ) -> DeliveryResult:
        self._controller.attempts.append("channel.send")
        if self._controller.consume("channel", "send", "before"):
            return DeliveryResult(ok=False, error="channel_unavailable")
        result = await self._inner.send(tenant, message)
        if result.ok:
            self._controller.record("channel.send")
            if self._controller.consume("channel", "send", "after"):
                return DeliveryResult(ok=False, error="channel_unavailable")
        return result

    def deliveries_for(self, tenant: TenantContext) -> tuple[OutboundReminder, ...]:
        return self._inner.deliveries_for(tenant)

    def tenant_ids_used(self) -> tuple[UUID, ...]:
        return self._inner.tenant_ids_used()


def instrument_channel(
    inner: FakeChannelAdapter, controller: FaultController
) -> InstrumentedChannel:
    return InstrumentedChannel(inner, controller)


class InstrumentedHandoffProvider:
    def __init__(
        self, inner: FakeHandoffAdapter, controller: FaultController
    ) -> None:
        self._inner = inner
        self._controller = controller

    async def transfer(
        self, tenant: TenantContext, payload: HandoffDelivery
    ) -> None:
        if self._controller.consume("handoff", "transfer", "before"):
            raise HandoffError(
                "provider_unavailable", "Handoff provider is unavailable."
            )
        await self._inner.transfer(tenant, payload)
        self._controller.record("handoff.transfer")
        if self._controller.consume("handoff", "transfer", "after"):
            raise HandoffError(
                "provider_unavailable", "Handoff provider is unavailable."
            )


def instrument_handoff_provider(
    inner: FakeHandoffAdapter, controller: FaultController
) -> InstrumentedHandoffProvider:
    return InstrumentedHandoffProvider(inner, controller)


class InstrumentedHandoffRepository:
    def __init__(
        self, inner: InMemoryHandoffRepository, controller: FaultController
    ) -> None:
        self._inner = inner
        self._controller = controller

    async def get(
        self, tenant: TenantContext, handoff_id: UUID
    ) -> HandoffCase | None:
        return await self._inner.get(tenant, handoff_id)

    async def get_by_business_key(
        self, tenant: TenantContext, business_key: str
    ) -> HandoffCase | None:
        return await self._inner.get_by_business_key(tenant, business_key)

    async def create_with_ownership(
        self,
        tenant: TenantContext,
        case: HandoffCase,
        outbox: HandoffOutbox,
        conversation_id: UUID,
    ) -> HandoffCase:
        if self._controller.consume("handoff", "persist", "before"):
            raise HandoffError(
                "upstream_unavailable", "Handoff store is unavailable."
            )
        stored = await self._inner.create_with_ownership(
            tenant, case, outbox, conversation_id
        )
        self._controller.record("handoff.persist")
        if self._controller.consume("handoff", "persist", "after"):
            raise HandoffError(
                "upstream_unavailable", "Handoff store is unavailable."
            )
        return stored


def instrument_handoff_repository(
    inner: InMemoryHandoffRepository, controller: FaultController
) -> InstrumentedHandoffRepository:
    return InstrumentedHandoffRepository(inner, controller)


class InstrumentedLLM:
    def __init__(self, decision: LLMDecision, controller: FaultController) -> None:
        self._decision = decision
        self._controller = controller
        self.requests: list[LLMRequest] = []

    async def generate(self, request: LLMRequest) -> LLMDecision:
        self.requests.append(request)
        if self._controller.consume("llm", "generate", "before"):
            raise LLMError("provider_unavailable", "LLM is unavailable.")
        self._controller.record("llm.generate")
        if self._controller.consume("llm", "generate", "after"):
            raise LLMError("provider_unavailable", "LLM is unavailable.")
        return self._decision


def instrument_llm(
    decision: LLMDecision, controller: FaultController
) -> InstrumentedLLM:
    return InstrumentedLLM(decision, controller)


class InstrumentedKnowledge:
    def __init__(
        self, hits: Sequence[KnowledgeHit], controller: FaultController
    ) -> None:
        self._hits = tuple(hits)
        self._controller = controller
        self.queries: list[KnowledgeQuery] = []

    async def search(
        self, tenant: TenantContext, query: KnowledgeQuery
    ) -> tuple[KnowledgeHit, ...]:
        del tenant
        self.queries.append(query)
        if self._controller.consume("kb", "search", "before"):
            raise KnowledgeError("unavailable", "Retrieval is unavailable.")
        self._controller.record("kb.search")
        if self._controller.consume("kb", "search", "after"):
            raise KnowledgeError("unavailable", "Retrieval is unavailable.")
        return self._hits


def instrument_kb(
    hits: Sequence[KnowledgeHit], controller: FaultController
) -> InstrumentedKnowledge:
    return InstrumentedKnowledge(hits, controller)


class _FakeConfigRepository:
    def __init__(self, configs: Mapping[UUID, TenantConfig]) -> None:
        self._configs = dict(configs)

    async def get_for_runtime(self, context: TenantContext) -> TenantConfig | None:
        return self._configs.get(context.tenant_id)


class _FakeConversationRepository:
    async def receive(
        self, tenant: TenantContext, message: InboundMessage
    ) -> ReceivedMessage:
        now = datetime.now(UTC)
        conversation_id = uuid4()
        conversation = Conversation(
            id=conversation_id,
            tenant_id=tenant.tenant_id,
            channel_integration_id=message.channel_integration_id,
            status="bot_owned",
            last_message_at=now,
            lock_version=1,
        )
        stored = Message(
            id=uuid4(),
            tenant_id=tenant.tenant_id,
            conversation_id=conversation_id,
            direction="inbound",
            external_message_id=message.external_message_id,
            content_type=message.content_type,
            occurred_at=message.occurred_at,
            received_at=now,
            dedupe_hash="hash",
        )
        session = SessionState(
            tenant_id=tenant.tenant_id,
            conversation_id=conversation_id,
            active_skill=None,
            active_workflow_id=None,
            state_version=1,
            expires_at=None,
        )
        return ReceivedMessage(
            conversation=conversation,
            message=stored,
            session=session,
            duplicate=False,
        )


class _FakeRunRepository:
    def __init__(self) -> None:
        self.started: list[AgentRun] = []
        self.finished: list[tuple[UUID, str]] = []

    async def start(
        self,
        tenant: TenantContext,
        conversation_id: UUID,
        input_message_id: UUID,
        *,
        skill: str | None = None,
        model_provider: str | None = None,
        model_name: str | None = None,
    ) -> AgentRun:
        run = AgentRun(
            id=uuid4(),
            tenant_id=tenant.tenant_id,
            conversation_id=conversation_id,
            config_version=tenant.config_version,
            correlation_id=tenant.correlation_id,
            input_message_id=input_message_id,
            status="started",
            started_at=datetime.now(UTC),
            finished_at=None,
            error_code=None,
            model_provider=model_provider,
            model_name=model_name,
            skill=skill,
        )
        self.started.append(run)
        return run

    async def finish(
        self,
        tenant: TenantContext,
        run_id: UUID,
        status: str,
        *,
        error_code: str | None = None,
        usage: dict[str, Any] | None = None,
        error_detail: str | None = None,
    ) -> AgentRunResult:
        del tenant, usage, error_detail
        self.finished.append((run_id, status))
        run = next(item for item in self.started if item.id == run_id)
        finished = AgentRun(
            id=run.id,
            tenant_id=run.tenant_id,
            conversation_id=run.conversation_id,
            config_version=run.config_version,
            correlation_id=run.correlation_id,
            input_message_id=run.input_message_id,
            status=status,  # type: ignore[arg-type]
            started_at=run.started_at,
            finished_at=datetime.now(UTC),
            error_code=error_code,
            model_provider=run.model_provider,
            model_name=run.model_name,
            skill=run.skill,
        )
        return AgentRunResult(
            run=finished,
            safe_message="An internal error occurred" if status == "failed" else None,
        )


def make_faq_harness(
    *,
    knowledge: InstrumentedKnowledge,
    llm: InstrumentedLLM,
) -> tuple[AgentHarness, _FakeRunRepository]:
    configs = _FakeConfigRepository(
        {
            _TENANT_A: TenantConfig(
                tenant_id=_TENANT_A,
                version=1,
                agent=AgentConfig(tone="cordial"),
                enabled_skills=frozenset({"faq"}),
            )
        }
    )
    runs = _FakeRunRepository()
    compiler = ContextCompiler(
        configs=configs,
        skills=SkillRegistry(),
        tenant_tools={_TENANT_A: frozenset({"appointments.create"})},
    )
    harness = AgentHarness(
        conversations=_FakeConversationRepository(),
        runs=runs,
        configs=configs,
        skills=SkillRegistry(),
        compiler=compiler,
        knowledge=knowledge,
        llm=llm,
    )
    return harness, runs
