from uuid import UUID

import pytest

from ia_mcp.agent_runtime.models import LLMDecision
from ia_mcp.configuration.models import AgentConfig, TenantConfig
from ia_mcp.knowledge.models import KnowledgeHit
from ia_mcp.mcp.registry import ToolName
from ia_mcp.skills.base import SkillTurn
from ia_mcp.skills.faq import AnswerPolicy, FAQSkill
from ia_mcp.tenancy.models import TenantContext

TENANT_A = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
DOC_A = UUID("aaaaaaaa-0000-4000-8000-000000000001")


def config() -> TenantConfig:
    return TenantConfig(
        tenant_id=TENANT_A,
        version=1,
        agent=AgentConfig(tone="cordial"),
        enabled_skills=frozenset({"faq"}),
    )


def hit(source_id: str = "src-a") -> KnowledgeHit:
    return KnowledgeHit(
        tenant_id=TENANT_A,
        source_id=source_id,
        text="Hours are 8 to 16.",
        score=0.9,
        document_id=DOC_A,
        document_version=1,
        page=1,
    )


def test_faq_exposes_no_tools() -> None:
    skill = FAQSkill()
    assert skill.name == "faq"
    assert skill.allowed_tools(config()) == frozenset()
    assert skill.required_fields(config()) == ()


def test_faq_allowed_tools_mirrors_enabled_tools_including_mutations() -> None:
    skill = FAQSkill()
    cfg = TenantConfig(
        tenant_id=TENANT_A,
        version=1,
        agent=AgentConfig(tone="cordial"),
        enabled_skills=frozenset({"faq"}),
        enabled_tools=frozenset(
            {"appointments.search", "appointments.create", "crear_turno"}
        ),
    )
    allowed = skill.allowed_tools(cfg)
    assert allowed == frozenset(
        {
            ToolName("appointments.search"),
            ToolName("appointments.create"),
            ToolName("crear_turno"),
        }
    )


@pytest.mark.anyio
async def test_faq_route_stays_on_faq_skill() -> None:
    tenant = TenantContext(
        tenant_id=TENANT_A,
        tenant_slug="tenant-a",
        config_version=1,
        correlation_id=UUID("33333333-3333-3333-3333-333333333333"),
    )
    result = await FAQSkill().route(SkillTurn(tenant=tenant, text="hours"))
    assert result.kind == "faq"


def test_answer_policy_requires_supported_hits() -> None:
    grounded = AnswerPolicy().apply(
        hits=(),
        decision=LLMDecision(kind="answer", text="made up", source_ids=("x",)),
    )
    assert grounded.kind == "insufficient"
    assert grounded.source_ids == ()


def test_answer_policy_drops_invented_sources() -> None:
    grounded = AnswerPolicy().apply(
        hits=(hit(),),
        decision=LLMDecision(
            kind="answer", text="open always", source_ids=("hallucinated",)
        ),
    )
    assert grounded.kind == "insufficient"
    assert grounded.source_ids == ()


def test_answer_policy_keeps_only_returned_source_ids() -> None:
    grounded = AnswerPolicy().apply(
        hits=(hit("src-a"), hit("src-b")),
        decision=LLMDecision(
            kind="answer",
            text="Hours are 8 to 16.",
            source_ids=("src-a", "src-b"),
        ),
    )
    assert grounded.kind == "answer"
    assert grounded.source_ids == ("src-a", "src-b")
