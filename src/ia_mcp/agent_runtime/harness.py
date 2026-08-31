import time
from collections.abc import Callable, Mapping, MutableMapping
from typing import Any, Protocol
from uuid import UUID

from ia_mcp.agent_runtime.context_compiler import ContextCompiler
from ia_mcp.agent_runtime.context_models import ContextRequest
from ia_mcp.agent_runtime.context_models import KnowledgeHit as ContextHit
from ia_mcp.agent_runtime.models import (
    AgentTurnResult,
    ExecutedToolCall,
    LLMDecision,
    LLMRequest,
    PolicyDecision,
    ToolObservation,
)
from ia_mcp.agent_runtime.observations import observation_from
from ia_mcp.agent_runtime.ports import (
    AgentRunRepository,
    ConversationReceiver,
    KnowledgeSearch,
    LLMError,
    LLMPort,
)
from ia_mcp.agent_runtime.run_repository import AgentRunStatus
from ia_mcp.configuration.models import TenantConfig
from ia_mcp.configuration.ports import ConfigurationError
from ia_mcp.contracts.common import ToolResult
from ia_mcp.conversation.models import InboundMessage
from ia_mcp.knowledge.models import KnowledgeHit, KnowledgeQuery
from ia_mcp.knowledge.ports import KnowledgeError
from ia_mcp.mcp.executor import ToolCall
from ia_mcp.mcp.registry import KNOWN_TOOLS
from ia_mcp.observability.propagation import start_span
from ia_mcp.observability.semconv import SPAN_AGENT_RUN, SPAN_LLM_GENERATE
from ia_mcp.skills.faq import SAFE_HANDOFF, SAFE_INSUFFICIENT, AnswerPolicy, FAQSkill
from ia_mcp.skills.registry import SkillNotAuthorized, SkillRegistry
from ia_mcp.tenancy.models import TenantContext

# Mechanical mirror of ToolExecutor._dispatch_capability: these names call
# _require_idempotency_key. This is the ADR-003 mutation mark, not a deny-list
# of authorization (ADR-005 keeps KNOWN_TOOLS as the canonical dispatch alias).
_CANONICAL_REQUIRING_IDEMPOTENCY = frozenset(
    {
        "appointments.create",
        "appointments.cancel",
        "appointments.reschedule",
        "appointments.confirm",
    }
)
_TURN_SKILL = "faq"
_FORBIDDEN_MESSAGE = "Action is not allowed."


class ConfigLookup(Protocol):
    async def get_for_runtime(self, context: TenantContext) -> TenantConfig | None: ...


class TurnToolExecutor(Protocol):
    async def execute(
        self,
        tenant: TenantContext,
        run_id: UUID,
        call: ToolCall,
        carrier: MutableMapping[str, str] | None = None,
    ) -> ToolResult[Any]: ...


class ToolExecutorFactory(Protocol):
    async def for_tenant(
        self, tenant: TenantContext, config: TenantConfig, skill: str
    ) -> TurnToolExecutor: ...


def canonical_requires_idempotency_key(name: str) -> bool:
    return name in _CANONICAL_REQUIRING_IDEMPOTENCY


def invocable_on_turn(
    name: str, *, declared_for_turn: frozenset[str] = frozenset()
) -> bool:
    """Fourth intersection term. Announced names are invocable this turn."""
    if name in declared_for_turn:
        return True
    if name in KNOWN_TOOLS:
        return not canonical_requires_idempotency_key(name)
    return False


def _freeze_arguments(arguments: Mapping[str, Any]) -> tuple[tuple[str, object], ...]:
    return tuple(
        sorted((key, _freeze_value(value)) for key, value in arguments.items())
    )


def _freeze_value(value: object) -> object:
    if isinstance(value, Mapping):
        return tuple(
            sorted((str(key), _freeze_value(item)) for key, item in value.items())
        )
    if isinstance(value, list | tuple):
        return tuple(_freeze_value(item) for item in value)
    return value


def _forbidden_observation(name: str) -> ToolObservation:
    return ToolObservation(
        name=name,
        ok=False,
        error_code="forbidden",
        safe_message=_FORBIDDEN_MESSAGE,
    )


class AgentHarness:
    def __init__(
        self,
        *,
        conversations: ConversationReceiver,
        runs: AgentRunRepository,
        configs: ConfigLookup,
        skills: SkillRegistry,
        compiler: ContextCompiler,
        knowledge: KnowledgeSearch,
        llm: LLMPort,
        executors: ToolExecutorFactory | None = None,
        max_tool_iterations: int = 4,
        turn_deadline_seconds: float = 30.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._conversations = conversations
        self._runs = runs
        self._configs = configs
        self._skills = skills
        self._compiler = compiler
        self._knowledge = knowledge
        self._llm = llm
        self._executors = executors
        self._max_tool_iterations = max_tool_iterations
        self._turn_deadline_seconds = turn_deadline_seconds
        self._clock = clock
        self._policy = AnswerPolicy()
        self._faq = FAQSkill()

    async def handle_message(
        self, tenant: TenantContext, message: InboundMessage
    ) -> AgentTurnResult:
        trajectory: list[str] = []
        received = await self._conversations.receive(tenant, message)
        trajectory.append("receive")
        if received.conversation.status == "human_owned":
            trajectory.append("guard")
            run = await self._runs.start(
                tenant,
                received.conversation.id,
                received.message.id,
                skill=None,
            )
            await self._runs.finish(tenant, run.id, "handed_off")
            return AgentTurnResult(
                kind="handoff",
                text=SAFE_HANDOFF,
                source_ids=(),
                tenant_id=tenant.tenant_id,
                run_id=run.id,
                trajectory=tuple(trajectory),
                tool_names=(),
            )
        config = await self._get_config(tenant)
        try:
            self._skills.resolve("faq", config)
        except SkillNotAuthorized:
            run = await self._runs.start(
                tenant,
                received.conversation.id,
                received.message.id,
                skill=None,
            )
            await self._runs.finish(tenant, run.id, "handed_off")
            return AgentTurnResult(
                kind="handoff",
                text=SAFE_HANDOFF,
                source_ids=(),
                tenant_id=tenant.tenant_id,
                run_id=run.id,
                trajectory=tuple(trajectory),
            )
        run = await self._runs.start(
            tenant,
            received.conversation.id,
            received.message.id,
            skill=self._faq.name,
            model_provider="fake",
            model_name="fake-llm",
        )
        with start_span(
            SPAN_AGENT_RUN,
            attributes={
                "run_id": str(run.id),
                "tenant_id": str(tenant.tenant_id),
                "config_version": tenant.config_version,
                "skill": self._faq.name,
            },
        ):
            try:
                hits = await self._knowledge.search(
                    tenant, KnowledgeQuery(text=message.text)
                )
                trajectory.append("search")
            except KnowledgeError:
                await self._runs.finish(
                    tenant, run.id, "failed", error_code="retrieval_unavailable"
                )
                return AgentTurnResult(
                    kind="insufficient",
                    text=SAFE_INSUFFICIENT,
                    source_ids=(),
                    tenant_id=tenant.tenant_id,
                    run_id=run.id,
                    trajectory=tuple(trajectory + ["search"]),
                )
            if not hits and not config.enabled_tools:
                grounded = self._policy.apply(hits=hits, decision=None)
                trajectory.append("policy")
                return await self._finish(
                    tenant, run.id, "succeeded", grounded, trajectory, ()
                )
            compiled = await self._compiler.compile(
                tenant,
                ContextRequest(
                    skill="faq",
                    knowledge_hits=tuple(
                        ContextHit(source_id=hit.source_id, text=hit.text)
                        for hit in hits
                    ),
                ),
            )
            trajectory.append("compile")
            tool_names = tuple(schema.name for schema in compiled.tool_schemas)
            allowed = tuple(hit.source_id for hit in hits)
            return await self._run_tool_loop(
                tenant,
                config,
                message,
                run.id,
                hits,
                compiled.core_instructions,
                compiled.knowledge,
                compiled.history,
                allowed,
                tool_names,
                trajectory,
            )

    async def _run_tool_loop(
        self,
        tenant: TenantContext,
        config: TenantConfig,
        message: InboundMessage,
        run_id: UUID,
        hits: tuple[KnowledgeHit, ...],
        instructions: str,
        knowledge: tuple[str, ...],
        history: tuple[str, ...],
        allowed: tuple[str, ...],
        tool_names: tuple[str, ...],
        trajectory: list[str],
    ) -> AgentTurnResult:
        observations: list[ToolObservation] = []
        executed: list[ExecutedToolCall] = []
        seen: set[tuple[str, object]] = set()
        forbidden_count = 0
        iteration = 0
        started = self._clock()
        executor: TurnToolExecutor | None = None
        loop_enabled = (
            self._executors is not None and self._max_tool_iterations > 0
        )

        while True:
            expired = await self._deadline_result(
                tenant, run_id, trajectory, tool_names, executed, started
            )
            if expired is not None:
                return expired
            try:
                with start_span(
                    SPAN_LLM_GENERATE,
                    attributes={
                        "run_id": str(run_id),
                        "tenant_id": str(tenant.tenant_id),
                        "config_version": tenant.config_version,
                        "skill": "faq",
                    },
                ):
                    decision = await self._llm.generate(
                        LLMRequest(
                            tenant_id=tenant.tenant_id,
                            skill="faq",
                            query=message.text,
                            instructions=instructions,
                            knowledge=knowledge,
                            history=history,
                            allowed_source_ids=allowed,
                            tool_names=tool_names,
                            tool_results=tuple(observations),
                            tone=config.agent.tone,
                            tenant_instructions=config.agent.instructions or None,
                        )
                    )
                trajectory.append("generate")
            except LLMError:
                return await self._provider_unavailable(
                    tenant, run_id, trajectory, tool_names, executed
                )
            expired = await self._deadline_result(
                tenant, run_id, trajectory, tool_names, executed, started
            )
            if expired is not None:
                return expired
            if isinstance(decision, LLMDecision):
                if (
                    any(call.ok for call in executed)
                    and decision.kind == "answer"
                    and decision.text
                ):
                    cited = tuple(
                        source for source in decision.source_ids if source in allowed
                    )
                    grounded = PolicyDecision(
                        kind="answer", text=decision.text, source_ids=cited
                    )
                else:
                    grounded = self._policy.apply(hits=hits, decision=decision)
                trajectory.append("policy")
                status: AgentRunStatus = (
                    "handed_off" if grounded.kind == "handoff" else "succeeded"
                )
                return await self._finish(
                    tenant,
                    run_id,
                    status,
                    grounded,
                    trajectory,
                    tool_names,
                    tool_calls=tuple(executed),
                )
            if not loop_enabled:
                return await self._fail_turn(
                    tenant,
                    run_id,
                    trajectory,
                    tool_names,
                    executed,
                    error_code="tool_budget_exhausted",
                )
            key = (decision.name, _freeze_arguments(decision.arguments))
            if key in seen:
                return await self._fail_turn(
                    tenant,
                    run_id,
                    trajectory,
                    tool_names,
                    executed,
                    error_code="tool_call_repeated",
                )
            if iteration >= self._max_tool_iterations:
                return await self._fail_turn(
                    tenant,
                    run_id,
                    trajectory,
                    tool_names,
                    executed,
                    error_code="tool_budget_exhausted",
                )
            if not invocable_on_turn(
                decision.name, declared_for_turn=frozenset(tool_names)
            ):
                observations.append(_forbidden_observation(decision.name))
                executed.append(
                    ExecutedToolCall(
                        name=decision.name, ok=False, error_code="forbidden"
                    )
                )
                forbidden_count += 1
                if forbidden_count >= 2:
                    return await self._handoff_turn(
                        tenant, run_id, trajectory, tool_names, executed
                    )
                iteration += 1
                continue
            if executor is None:
                assert self._executors is not None
                executor = await self._executors.for_tenant(
                    tenant, config, _TURN_SKILL
                )
            result = await executor.execute(
                tenant,
                run_id,
                ToolCall(name=decision.name, arguments=dict(decision.arguments)),
            )
            seen.add(key)
            error_code = (
                None
                if result.ok or result.error is None
                else result.error.code.value
            )
            recorded = ExecutedToolCall(
                name=decision.name, ok=result.ok, error_code=error_code
            )
            executed.append(recorded)
            if error_code == "tenant_isolation_violation":
                return await self._fail_turn(
                    tenant,
                    run_id,
                    trajectory,
                    tool_names,
                    executed,
                    error_code="tenant_isolation_violation",
                )
            observations.append(observation_from(decision.name, result))
            if error_code == "forbidden":
                forbidden_count += 1
                if forbidden_count >= 2:
                    return await self._handoff_turn(
                        tenant, run_id, trajectory, tool_names, executed
                    )
            iteration += 1

    async def _deadline_result(
        self,
        tenant: TenantContext,
        run_id: UUID,
        trajectory: list[str],
        tool_names: tuple[str, ...],
        executed: list[ExecutedToolCall],
        started: float,
    ) -> AgentTurnResult | None:
        if self._clock() - started < self._turn_deadline_seconds:
            return None
        return await self._fail_turn(
            tenant,
            run_id,
            trajectory,
            tool_names,
            executed,
            error_code="turn_deadline_exceeded",
        )

    async def _provider_unavailable(
        self,
        tenant: TenantContext,
        run_id: UUID,
        trajectory: list[str],
        tool_names: tuple[str, ...],
        executed: list[ExecutedToolCall],
    ) -> AgentTurnResult:
        await self._runs.finish(
            tenant, run_id, "failed", error_code="provider_unavailable"
        )
        return AgentTurnResult(
            kind="insufficient",
            text=SAFE_INSUFFICIENT,
            source_ids=(),
            tenant_id=tenant.tenant_id,
            run_id=run_id,
            trajectory=tuple(trajectory),
            tool_names=tool_names,
            tool_calls=tuple(executed),
        )

    async def _fail_turn(
        self,
        tenant: TenantContext,
        run_id: UUID,
        trajectory: list[str],
        tool_names: tuple[str, ...],
        executed: list[ExecutedToolCall],
        *,
        error_code: str,
    ) -> AgentTurnResult:
        grounded = PolicyDecision(
            kind="insufficient", text=SAFE_INSUFFICIENT, source_ids=()
        )
        return await self._finish(
            tenant,
            run_id,
            "failed",
            grounded,
            trajectory,
            tool_names,
            tool_calls=tuple(executed),
            error_code=error_code,
        )

    async def _handoff_turn(
        self,
        tenant: TenantContext,
        run_id: UUID,
        trajectory: list[str],
        tool_names: tuple[str, ...],
        executed: list[ExecutedToolCall],
    ) -> AgentTurnResult:
        trajectory.append("policy")
        grounded = PolicyDecision(kind="handoff", text=SAFE_HANDOFF, source_ids=())
        return await self._finish(
            tenant,
            run_id,
            "handed_off",
            grounded,
            trajectory,
            tool_names,
            tool_calls=tuple(executed),
        )

    async def _get_config(self, tenant: TenantContext) -> TenantConfig:
        config = await self._configs.get_for_runtime(tenant)
        if config is None:
            raise ConfigurationError(
                "not_found", "Active configuration is not available."
            )
        return config

    async def _finish(
        self,
        tenant: TenantContext,
        run_id: UUID,
        status: AgentRunStatus,
        grounded: PolicyDecision,
        trajectory: list[str],
        tool_names: tuple[str, ...],
        *,
        tool_calls: tuple[ExecutedToolCall, ...] = (),
        error_code: str | None = None,
    ) -> AgentTurnResult:
        finished = await self._runs.finish(
            tenant, run_id, status, error_code=error_code
        )
        return AgentTurnResult(
            kind=grounded.kind,
            text=grounded.text,
            source_ids=grounded.source_ids,
            tenant_id=tenant.tenant_id,
            run_id=finished.run.id,
            trajectory=tuple(trajectory),
            tool_names=tool_names,
            tool_calls=tool_calls,
        )
