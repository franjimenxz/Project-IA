from typing import Any, Protocol
from uuid import UUID

from ia_mcp.agent_runtime.models import LLMDecision, LLMRequest
from ia_mcp.agent_runtime.run_repository import AgentRun, AgentRunResult, AgentRunStatus
from ia_mcp.conversation.models import InboundMessage, ReceivedMessage
from ia_mcp.knowledge.models import KnowledgeHit, KnowledgeQuery
from ia_mcp.tenancy.models import TenantContext


class LLMError(Exception):
    def __init__(self, code: str, safe_message: str) -> None:
        self.code = code
        self.safe_message = safe_message
        super().__init__(safe_message)


class LLMPort(Protocol):
    async def generate(self, request: LLMRequest) -> LLMDecision: ...


class FakeLLM:
    def __init__(self, decision: LLMDecision) -> None:
        self._decision = decision

    async def generate(self, request: LLMRequest) -> LLMDecision:
        del request
        return self._decision


class ConversationReceiver(Protocol):
    async def receive(
        self, tenant: TenantContext, message: InboundMessage
    ) -> ReceivedMessage: ...


class AgentRunRepository(Protocol):
    async def start(
        self,
        tenant: TenantContext,
        conversation_id: UUID,
        input_message_id: UUID,
        *,
        skill: str | None = None,
        model_provider: str | None = None,
        model_name: str | None = None,
    ) -> AgentRun: ...

    async def finish(
        self,
        tenant: TenantContext,
        run_id: UUID,
        status: AgentRunStatus,
        *,
        error_code: str | None = None,
        usage: dict[str, Any] | None = None,
        error_detail: str | None = None,
    ) -> AgentRunResult: ...


class KnowledgeSearch(Protocol):
    async def search(
        self, tenant: TenantContext, query: KnowledgeQuery
    ) -> tuple[KnowledgeHit, ...]: ...
