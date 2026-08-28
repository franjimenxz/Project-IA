from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

type ConversationStatus = Literal["bot_owned", "human_owned", "closed"]
type MessageDirection = Literal["inbound", "outbound"]
type ContentType = Literal["text", "document", "interactive", "system"]


@dataclass(frozen=True, slots=True)
class InboundMessage:
    channel: str
    channel_account_id: str
    channel_integration_id: UUID
    external_message_id: str
    external_user_id: str
    text: str
    occurred_at: datetime
    content_type: ContentType = "text"


@dataclass(frozen=True, slots=True)
class Conversation:
    id: UUID
    tenant_id: UUID
    channel_integration_id: UUID
    status: ConversationStatus
    last_message_at: datetime
    lock_version: int


@dataclass(frozen=True, slots=True)
class Message:
    id: UUID
    tenant_id: UUID
    conversation_id: UUID
    direction: MessageDirection
    external_message_id: str
    content_type: ContentType
    occurred_at: datetime
    received_at: datetime
    dedupe_hash: str


@dataclass(frozen=True, slots=True)
class SessionState:
    tenant_id: UUID
    conversation_id: UUID
    active_skill: str | None
    active_workflow_id: UUID | None
    state_version: int
    expires_at: datetime | None


@dataclass(frozen=True, slots=True)
class ReceivedMessage:
    conversation: Conversation
    message: Message
    session: SessionState
    duplicate: bool
