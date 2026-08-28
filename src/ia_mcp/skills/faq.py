from ia_mcp.agent_runtime.models import LLMDecision, PolicyDecision
from ia_mcp.configuration.models import SkillName, TenantConfig
from ia_mcp.knowledge.models import KnowledgeHit
from ia_mcp.mcp.registry import ToolName
from ia_mcp.skills.base import FieldSpec, SkillResult, SkillTurn

SAFE_INSUFFICIENT = (
    "I don't have enough information to answer from the available sources."
)
SAFE_HANDOFF = "I'll connect you with a person who can help."
SAFE_CLARIFY = "Could you rephrase the question?"


class AnswerPolicy:
    def apply(
        self,
        *,
        hits: tuple[KnowledgeHit, ...],
        decision: LLMDecision | None,
        fallback: str = "insufficient",
    ) -> PolicyDecision:
        allowed = {hit.source_id for hit in hits}
        if not allowed or decision is None:
            return PolicyDecision(kind=fallback, text=SAFE_INSUFFICIENT, source_ids=())  # type: ignore[arg-type]
        cited = tuple(source for source in decision.source_ids if source in allowed)
        invented = tuple(source for source in decision.source_ids if source not in allowed)
        if decision.kind == "answer":
            if not cited or invented:
                return PolicyDecision(
                    kind=fallback,  # type: ignore[arg-type]
                    text=SAFE_INSUFFICIENT,
                    source_ids=(),
                )
            return PolicyDecision(
                kind="answer", text=decision.text, source_ids=cited
            )
        if decision.kind == "handoff":
            return PolicyDecision(kind="handoff", text=SAFE_HANDOFF, source_ids=())
        if decision.kind == "clarify":
            return PolicyDecision(kind="clarify", text=SAFE_CLARIFY, source_ids=cited)
        return PolicyDecision(kind="insufficient", text=SAFE_INSUFFICIENT, source_ids=())


class FAQSkill:
    name: SkillName = "faq"

    def required_fields(self, config: TenantConfig) -> tuple[FieldSpec, ...]:
        del config
        return ()

    def allowed_tools(self, config: TenantConfig) -> frozenset[ToolName]:
        del config
        return frozenset()

    async def route(self, turn: SkillTurn) -> SkillResult:
        del turn
        return SkillResult(kind="faq")
