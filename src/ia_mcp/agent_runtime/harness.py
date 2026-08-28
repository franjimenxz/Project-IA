from typing import Protocol
from uuid import UUID

from ia_mcp.agent_runtime.context_compiler import ContextCompiler
from ia_mcp.agent_runtime.context_models import ContextRequest
from ia_mcp.agent_runtime.context_models import KnowledgeHit as ContextHit
from ia_mcp.agent_runtime.models import AgentTurnResult, LLMRequest, PolicyDecision
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
from ia_mcp.conversation.models import InboundMessage
from ia_mcp.knowledge.models import KnowledgeQuery
from ia_mcp.knowledge.ports import KnowledgeError
from ia_mcp.skills.faq import SAFE_HANDOFF, SAFE_INSUFFICIENT, AnswerPolicy, FAQSkill
from ia_mcp.skills.registry import SkillNotAuthorized, SkillRegistry
from ia_mcp.tenancy.models import TenantContext


class ConfigLookup(Protocol):
    async def get_for_runtime(self, context: TenantContext) -> TenantConfig | None: ...


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
    ) -> None:
        self._conversations = conversations
        self._runs = runs
        self._configs = configs
        self._skills = skills
        self._compiler = compiler
        self._knowledge = knowledge
        self._llm = llm
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
        if not hits:
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
                    ContextHit(source_id=hit.source_id, text=hit.text) for hit in hits
                ),
            ),
        )
        trajectory.append("compile")
        tool_names = tuple(schema.name for schema in compiled.tool_schemas)
        allowed = tuple(hit.source_id for hit in hits)
        try:
            decision = await self._llm.generate(
                LLMRequest(
                    tenant_id=tenant.tenant_id,
                    skill="faq",
                    query=message.text,
                    instructions=compiled.core_instructions,
                    knowledge=compiled.knowledge,
                    history=compiled.history,
                    allowed_source_ids=allowed,
                    tool_names=tool_names,
                )
            )
            trajectory.append("generate")
        except LLMError:
            await self._runs.finish(
                tenant, run.id, "failed", error_code="provider_unavailable"
            )
            return AgentTurnResult(
                kind="insufficient",
                text=SAFE_INSUFFICIENT,
                source_ids=(),
                tenant_id=tenant.tenant_id,
                run_id=run.id,
                trajectory=tuple(trajectory),
                tool_names=tool_names,
            )
        grounded = self._policy.apply(hits=hits, decision=decision)
        trajectory.append("policy")
        status: AgentRunStatus = (
            "handed_off" if grounded.kind == "handoff" else "succeeded"
        )
        return await self._finish(
            tenant, run.id, status, grounded, trajectory, tool_names
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
    ) -> AgentTurnResult:
        finished = await self._runs.finish(tenant, run_id, status)
        return AgentTurnResult(
            kind=grounded.kind,
            text=grounded.text,
            source_ids=grounded.source_ids,
            tenant_id=tenant.tenant_id,
            run_id=finished.run.id,
            trajectory=tuple(trajectory),
            tool_names=tool_names,
        )
