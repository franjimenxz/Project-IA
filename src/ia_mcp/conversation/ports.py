from typing import Protocol
from uuid import UUID

from ia_mcp.conversation.models import (
    Conversation,
    InboundMessage,
    Message,
    ReceivedMessage,
    SessionState,
)
from ia_mcp.tenancy.models import TenantContext


class ConversationError(Exception):
    def __init__(self, code: str, safe_message: str) -> None:
        self.code = code
        self.safe_message = safe_message
        super().__init__(safe_message)


class ConversationRepository(Protocol):
    async def receive(
        self, tenant: TenantContext, message: InboundMessage
    ) -> ReceivedMessage: ...

    async def get(
        self, tenant: TenantContext, conversation_id: UUID
    ) -> Conversation | None: ...

    async def get_session(
        self, tenant: TenantContext, conversation_id: UUID
    ) -> SessionState | None: ...

    async def get_message(
        self, tenant: TenantContext, message_id: UUID
    ) -> Message | None: ...

    async def cas_update_session(
        self,
        tenant: TenantContext,
        conversation_id: UUID,
        expected_version: int,
        *,
        active_skill: str | None,
    ) -> SessionState: ...
