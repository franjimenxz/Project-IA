from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Never, Protocol
from uuid import UUID, uuid4

from ia_mcp.agent_runtime.context_compiler import ContextCompiler
from ia_mcp.agent_runtime.harness import AgentHarness
from ia_mcp.agent_runtime.models import (
    AgentTurnResult,
    AnswerKind,
    LLMDecision,
    LLMRequest,
)
from ia_mcp.agent_runtime.run_repository import AgentRun, AgentRunResult
from ia_mcp.configuration.models import AgentConfig, TenantConfig
from ia_mcp.conversation.models import (
    Conversation,
    InboundMessage,
    Message,
    ReceivedMessage,
    SessionState,
)
from ia_mcp.evals.models import EvalCase, EvalOutcome
from ia_mcp.evals.scorers import (
    TENANT_FIXTURE_IDS,
    ObservedToolCall,
    ObservedTrajectory,
)
from ia_mcp.knowledge.models import KnowledgeHit, KnowledgeQuery
from ia_mcp.skills.faq import SAFE_HANDOFF, SAFE_INSUFFICIENT
from ia_mcp.skills.registry import SkillRegistry
from ia_mcp.tenancy.models import TenantContext

_CHANNEL_A = UUID("aa111111-1111-1111-1111-111111111111")
_CHANNEL_B = UUID("bb111111-1111-1111-1111-111111111111")
_CORR_A = UUID("33333333-3333-3333-3333-333333333333")
_CORR_B = UUID("44444444-4444-4444-4444-444444444444")
_DOC = UUID("aaaaaaaa-0000-4000-8000-000000000001")


class HarnessPort(Protocol):
    async def handle_message(
        self, tenant: TenantContext, message: InboundMessage
    ) -> AgentTurnResult: ...


class _ConfigLookup:
    def __init__(self, configs: dict[UUID, TenantConfig]) -> None:
        self._configs = configs

    async def get_for_runtime(self, context: TenantContext) -> TenantConfig | None:
        return self._configs.get(context.tenant_id)


class _ConversationReceiver:
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
            dedupe_hash="eval",
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


class _RunRepository:
    def __init__(self) -> None:
        self.started: list[AgentRun] = []

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
        usage: dict[str, object] | None = None,
        error_detail: str | None = None,
    ) -> AgentRunResult:
        del tenant, usage, error_detail
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
        return AgentRunResult(run=finished, safe_message=None)


class MutableKnowledge:
    def __init__(self) -> None:
        self.hits: tuple[KnowledgeHit, ...] = ()

    async def search(
        self, tenant: TenantContext, query: KnowledgeQuery
    ) -> tuple[KnowledgeHit, ...]:
        del query
        return tuple(hit for hit in self.hits if hit.tenant_id == tenant.tenant_id)


class MutableLLM:
    def __init__(self) -> None:
        self.decision = LLMDecision(
            kind="insufficient",
            text=SAFE_INSUFFICIENT,
            source_ids=(),
        )
        self.requests: list[LLMRequest] = []

    async def generate(self, request: LLMRequest) -> LLMDecision:
        self.requests.append(request)
        return self.decision


def summarize_compiled_context(
    *,
    skill: str,
    config_version: int,
    knowledge_blocks: int,
    tool_names: tuple[str, ...],
    instructions: str | None = None,
) -> str:
    del instructions
    tools = ",".join(tool_names) if tool_names else "none"
    return (
        f"skill={skill} config_version={config_version} "
        f"knowledge_blocks={knowledge_blocks} tools={tools}"
    )


def tenant_context_for(fixture: str, config_version: int) -> TenantContext:
    tenant_id = TENANT_FIXTURE_IDS[fixture]
    if fixture == "tenant_a":
        return TenantContext(
            tenant_id=tenant_id,
            tenant_slug="tenant-a",
            config_version=config_version,
            correlation_id=_CORR_A,
        )
    if fixture == "tenant_b":
        return TenantContext(
            tenant_id=tenant_id,
            tenant_slug="tenant-b",
            config_version=config_version,
            correlation_id=_CORR_B,
        )
    exhaustive: str = fixture
    raise ValueError(f"unknown tenant fixture: {exhaustive}")


def load_eval_cases(path: Path) -> tuple[EvalCase, ...]:
    cases: list[EvalCase] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            cases.append(EvalCase.model_validate(json.loads(line)))
    return tuple(cases)


def select_suite(cases: tuple[EvalCase, ...], suite: str) -> tuple[EvalCase, ...]:
    if suite == "smoke":
        return tuple(case for case in cases if case.expected_skill == "faq")
    if suite == "all":
        return cases
    raise ValueError(f"unknown suite: {suite}")


class EvalRunner:
    def __init__(
        self,
        harness: HarnessPort,
        *,
        knowledge: MutableKnowledge | None = None,
        llm: MutableLLM | None = None,
        runs: _RunRepository | None = None,
    ) -> None:
        self.harness = harness
        self.knowledge = knowledge
        self.llm = llm
        self._runs = runs

    @classmethod
    def for_fake_provider(cls) -> EvalRunner:
        knowledge = MutableKnowledge()
        llm = MutableLLM()
        runs = _RunRepository()
        configs = _ConfigLookup(
            {
                tenant_id: TenantConfig(
                    tenant_id=tenant_id,
                    version=1,
                    agent=AgentConfig(tone="cordial"),
                    enabled_skills=frozenset({"faq"}),
                )
                for tenant_id in TENANT_FIXTURE_IDS.values()
            }
        )
        compiler = ContextCompiler(
            configs=configs,
            skills=SkillRegistry(),
            tenant_tools={tenant_id: frozenset() for tenant_id in TENANT_FIXTURE_IDS.values()},
        )
        harness = AgentHarness(
            conversations=_ConversationReceiver(),
            runs=runs,
            configs=configs,
            skills=SkillRegistry(),
            compiler=compiler,
            knowledge=knowledge,
            llm=llm,
        )
        return cls(harness, knowledge=knowledge, llm=llm, runs=runs)

    async def run_case(self, case: EvalCase) -> ObservedTrajectory:
        tenant = tenant_context_for(case.tenant_fixture, case.config_version)
        self._prepare_fake(case, tenant)
        started = time.perf_counter()
        result = await self.harness.handle_message(tenant, _inbound_for(case, tenant))
        latency_ms = (time.perf_counter() - started) * 1000
        return observe_turn(case, tenant, result, runs=self._runs, latency_ms=latency_ms)

    async def run_suite(self, cases: tuple[EvalCase, ...]) -> tuple[ObservedTrajectory, ...]:
        observed: list[ObservedTrajectory] = []
        for case in cases:
            observed.append(await self.run_case(case))
        return tuple(observed)

    def _prepare_fake(self, case: EvalCase, tenant: TenantContext) -> None:
        if self.knowledge is None or self.llm is None:
            return
        sources = tuple(sorted(case.allowed_sources))
        self.knowledge.hits = tuple(_hit(tenant.tenant_id, source_id) for source_id in sources)
        if case.expected_outcome == EvalOutcome.ANSWER:
            self.llm.decision = LLMDecision(
                kind="answer",
                text="Synthetic grounded answer.",
                source_ids=sources,
            )
            return
        if case.expected_outcome == EvalOutcome.CLARIFY:
            self.llm.decision = LLMDecision(kind="clarify", text="clarify", source_ids=sources)
            return
        if case.expected_outcome == EvalOutcome.HANDOFF:
            self.llm.decision = LLMDecision(kind="handoff", text=SAFE_HANDOFF, source_ids=())
            return
        if case.expected_outcome == EvalOutcome.INSUFFICIENT:
            if not sources:
                self.knowledge.hits = ()
            self.llm.decision = LLMDecision(
                kind="insufficient",
                text=SAFE_INSUFFICIENT,
                source_ids=(),
            )
            return
        self.knowledge.hits = ()
        self.llm.decision = LLMDecision(
            kind="insufficient",
            text=SAFE_INSUFFICIENT,
            source_ids=(),
        )


def observe_turn(
    case: EvalCase,
    tenant: TenantContext,
    result: AgentTurnResult,
    *,
    runs: _RunRepository | None = None,
    latency_ms: float | None = None,
) -> ObservedTrajectory:
    recorded_skill = runs.started[-1].skill if runs is not None and runs.started else None
    skill = recorded_skill or _skill_from_kind(result.kind)
    roles = ",".join(message.role for message in case.messages)
    return ObservedTrajectory(
        case_id=case.case_id,
        tenant_fixture=case.tenant_fixture,
        tenant_id=tenant.tenant_id,
        config_version=tenant.config_version,
        input_summary=f"messages={len(case.messages)} roles={roles}",
        compiled_context_summary=summarize_compiled_context(
            skill=skill or "none",
            config_version=tenant.config_version,
            knowledge_blocks=len(result.source_ids),
            tool_names=result.tool_names,
        ),
        retrieval_source_ids=frozenset(result.source_ids),
        skill=skill,
        tool_calls=tuple(ObservedToolCall(name=name) for name in result.tool_names),
        workflow_state=None,
        workflow_transitions=(),
        handoff=result.kind == "handoff",
        outcome=_outcome_from_kind(result.kind),
        latency_ms=latency_ms,
        usage={},
    )


def _inbound_for(case: EvalCase, tenant: TenantContext) -> InboundMessage:
    text = next(
        (message.text for message in reversed(case.messages) if message.role == "user"),
        case.messages[-1].text,
    )
    channel_id = _CHANNEL_A if case.tenant_fixture == "tenant_a" else _CHANNEL_B
    return InboundMessage(
        channel="simulated",
        channel_account_id=tenant.tenant_slug,
        channel_integration_id=channel_id,
        external_message_id=str(uuid4()),
        external_user_id=f"{tenant.tenant_slug}-eval",
        text=text,
        occurred_at=datetime.now(UTC),
    )


def _hit(tenant_id: UUID, source_id: str) -> KnowledgeHit:
    return KnowledgeHit(
        tenant_id=tenant_id,
        source_id=source_id,
        text="Synthetic catalog snippet.",
        score=0.9,
        document_id=_DOC,
        document_version=1,
        page=1,
    )


def _outcome_from_kind(kind: AnswerKind) -> EvalOutcome:
    if kind == "answer":
        return EvalOutcome.ANSWER
    if kind == "clarify":
        return EvalOutcome.CLARIFY
    if kind == "insufficient":
        return EvalOutcome.INSUFFICIENT
    if kind == "handoff":
        return EvalOutcome.HANDOFF
    exhaustive: Never = kind
    raise ValueError(f"unsupported turn kind: {exhaustive}")


def _skill_from_kind(kind: AnswerKind) -> str:
    if kind == "handoff":
        return "human_handoff"
    if kind == "answer":
        return "faq"
    if kind == "clarify":
        return "faq"
    if kind == "insufficient":
        return "faq"
    exhaustive: Never = kind
    raise ValueError(f"unsupported turn kind: {exhaustive}")
