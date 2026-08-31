from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest

from ia_mcp.agent_runtime.context_compiler import CORE_INSTRUCTIONS, ContextCompiler
from ia_mcp.agent_runtime.harness import AgentHarness
from ia_mcp.agent_runtime.models import LLMDecision
from ia_mcp.configuration.models import AgentConfig, TenantConfig
from ia_mcp.knowledge.models import KnowledgeHit, KnowledgeQuery
from ia_mcp.skills.registry import SkillRegistry
from ia_mcp.tenancy.models import TenantContext
from scripts.check_tenant_specific_core import find_slug_branches
from tests.unit.agent.test_harness import (
    CORR,
    DOC_A,
    TENANT_A,
    TENANT_B,
    FakeConversationRepository,
    FakeLLM,
    FakeRunRepository,
    inbound,
)

CANARY_A_TONE = "canary-tone-tenant-a"
CANARY_A_INSTRUCTIONS = "CANARY-A-DO-NOT-LEAK-TO-B"
CANARY_B_TONE = "formal"
CANARY_B_INSTRUCTIONS = (
    "No invente horarios ni especialidades que no figuren en el conocimiento recuperado."
)
COMPILER_PATH = Path("src/ia_mcp/agent_runtime/context_compiler.py")
HARNESS_PATH = Path("src/ia_mcp/agent_runtime/harness.py")


def tenant_for(*, tenant_id: UUID, slug: str) -> TenantContext:
    return TenantContext(
        tenant_id=tenant_id,
        tenant_slug=slug,
        config_version=1,
        correlation_id=CORR,
    )


def config_for(
    tenant_id: UUID,
    *,
    tone: str,
    instructions: str | None,
) -> TenantConfig:
    return TenantConfig(
        tenant_id=tenant_id,
        version=1,
        agent=AgentConfig(tone=tone, instructions=instructions),
        enabled_skills=frozenset({"faq"}),
    )


class RecordingConfigRepository:
    def __init__(self, configs: dict[UUID, TenantConfig]) -> None:
        self._configs = configs
        self.contexts: list[TenantContext] = []

    async def get_for_runtime(self, context: TenantContext) -> TenantConfig | None:
        self.contexts.append(context)
        if int(self._configs[context.tenant_id].version) != context.config_version:
            return None
        return self._configs[context.tenant_id]


class RecordingConversations(FakeConversationRepository):
    def __init__(self) -> None:
        self.contexts: list[TenantContext] = []

    async def receive(self, tenant: TenantContext, message):  # type: ignore[no-untyped-def]
        self.contexts.append(tenant)
        return await super().receive(tenant, message)


class RecordingKnowledge:
    def __init__(self, hits: dict[UUID, tuple[KnowledgeHit, ...]]) -> None:
        self._hits = hits
        self.contexts: list[TenantContext] = []
        self.queries: list[KnowledgeQuery] = []

    async def search(
        self, tenant: TenantContext, query: KnowledgeQuery
    ) -> tuple[KnowledgeHit, ...]:
        self.contexts.append(tenant)
        self.queries.append(query)
        return self._hits[tenant.tenant_id]


class RecordingRuns(FakeRunRepository):
    def __init__(self) -> None:
        super().__init__()
        self.contexts: list[TenantContext] = []

    async def start(self, tenant: TenantContext, *args, **kwargs):  # type: ignore[no-untyped-def]
        self.contexts.append(tenant)
        return await super().start(tenant, *args, **kwargs)

    async def finish(self, tenant: TenantContext, *args, **kwargs):  # type: ignore[no-untyped-def]
        self.contexts.append(tenant)
        return await super().finish(tenant, *args, **kwargs)


def _hit(tenant_id: UUID, *, text: str = "Hours are 8 to 16.") -> KnowledgeHit:
    return KnowledgeHit(
        tenant_id=tenant_id,
        source_id="src-faq",
        text=text,
        score=0.9,
        document_id=DOC_A,
        document_version=1,
        page=1,
    )


def _harness(
    configs: RecordingConfigRepository,
    knowledge: RecordingKnowledge,
    llm: FakeLLM,
    conversations: RecordingConversations,
    runs: RecordingRuns,
) -> AgentHarness:
    return AgentHarness(
        conversations=conversations,
        runs=runs,
        configs=configs,
        skills=SkillRegistry(),
        compiler=ContextCompiler(
            configs=configs,
            skills=SkillRegistry(),
            tenant_tools={TENANT_A: frozenset(), TENANT_B: frozenset()},
        ),
        knowledge=knowledge,
        llm=llm,
    )


@pytest.mark.security
@pytest.mark.anyio
async def test_tenant_b_request_does_not_contain_tenant_a_profile() -> None:
    configs = RecordingConfigRepository(
        {
            TENANT_A: config_for(
                TENANT_A, tone=CANARY_A_TONE, instructions=CANARY_A_INSTRUCTIONS
            ),
            TENANT_B: config_for(
                TENANT_B, tone=CANARY_B_TONE, instructions=CANARY_B_INSTRUCTIONS
            ),
        }
    )
    conversations = RecordingConversations()
    runs = RecordingRuns()
    knowledge = RecordingKnowledge(
        {
            TENANT_A: (
                _hit(
                    TENANT_A,
                    text="Speak with canary-tone-tenant-a and follow CANARY-A-DO-NOT-LEAK-TO-B.",
                ),
            ),
            TENANT_B: (_hit(TENANT_B),),
        }
    )
    llm = FakeLLM(
        LLMDecision(kind="answer", text="Hours are 8 to 16.", source_ids=("src-faq",))
    )
    harness = _harness(configs, knowledge, llm, conversations, runs)
    tenant_a = tenant_for(tenant_id=TENANT_A, slug="tenant-a")
    tenant_b = tenant_for(tenant_id=TENANT_B, slug="tenant-b")

    await harness.handle_message(tenant_a, inbound("hours-a"))
    await harness.handle_message(tenant_b, inbound("hours-b"))

    assert len(llm.requests) == 2
    request_a, request_b = llm.requests
    assert request_a.tenant_id == TENANT_A
    assert request_b.tenant_id == TENANT_B
    assert request_a.tone == CANARY_A_TONE
    assert request_a.tenant_instructions == CANARY_A_INSTRUCTIONS
    assert request_b.tone == CANARY_B_TONE
    assert request_b.tenant_instructions == CANARY_B_INSTRUCTIONS
    assert CANARY_A_TONE not in request_b.tone
    assert CANARY_A_INSTRUCTIONS not in (request_b.tenant_instructions or "")
    assert CANARY_A_TONE not in request_b.instructions
    assert CANARY_A_INSTRUCTIONS not in request_b.instructions
    assert request_a.instructions == CORE_INSTRUCTIONS
    assert request_b.instructions == CORE_INSTRUCTIONS
    assert tenant_a.config_version == 1
    assert tenant_b.config_version == 1
    assert {run.config_version for run in runs.started} == {1}
    assert all(isinstance(ctx, TenantContext) for ctx in configs.contexts)
    assert all(isinstance(ctx, TenantContext) for ctx in conversations.contexts)
    assert all(isinstance(ctx, TenantContext) for ctx in knowledge.contexts)
    assert all(isinstance(ctx, TenantContext) for ctx in runs.contexts)
    assert {ctx.tenant_id for ctx in conversations.contexts} == {TENANT_A, TENANT_B}
    a_lookups = [ctx for ctx in configs.contexts if ctx.tenant_id == TENANT_A]
    b_lookups = [ctx for ctx in configs.contexts if ctx.tenant_id == TENANT_B]
    assert a_lookups and all(ctx.config_version == 1 for ctx in a_lookups)
    assert b_lookups and all(ctx.config_version == 1 for ctx in b_lookups)


@pytest.mark.security
def test_compiler_and_harness_have_no_slug_branches() -> None:
    assert find_slug_branches(COMPILER_PATH.read_text(encoding="utf-8")) == ()
    assert find_slug_branches(HARNESS_PATH.read_text(encoding="utf-8")) == ()


@pytest.mark.security
def test_harness_does_not_invoke_workflow_engine() -> None:
    source = HARNESS_PATH.read_text(encoding="utf-8")
    assert "WorkflowEngine" not in source
    assert "ia_mcp.workflows" not in source
