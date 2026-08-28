from __future__ import annotations

import asyncio
from uuid import UUID

from ia_mcp.conversation.models import Conversation
from ia_mcp.handoff.models import HandoffCase, HandoffOutbox
from ia_mcp.handoff.ports import HandoffError
from ia_mcp.tenancy.models import TenantContext


class InMemoryHandoffRepository:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._conversations: dict[tuple[UUID, UUID], Conversation] = {}
        self._cases: dict[tuple[UUID, UUID], HandoffCase] = {}
        self._by_key: dict[tuple[UUID, str], UUID] = {}
        self._outbox: list[HandoffOutbox] = []

    def seed_conversation(self, conversation: Conversation) -> None:
        self._conversations[(conversation.tenant_id, conversation.id)] = conversation

    async def get(self, tenant: TenantContext, handoff_id: UUID) -> HandoffCase | None:
        async with self._lock:
            return self._cases.get((tenant.tenant_id, handoff_id))

    async def get_by_business_key(
        self, tenant: TenantContext, business_key: str
    ) -> HandoffCase | None:
        async with self._lock:
            handoff_id = self._by_key.get((tenant.tenant_id, business_key))
            if handoff_id is None:
                return None
            return self._cases.get((tenant.tenant_id, handoff_id))

    async def conversation_status(
        self, tenant: TenantContext, conversation_id: UUID
    ) -> str | None:
        async with self._lock:
            conversation = self._conversations.get((tenant.tenant_id, conversation_id))
            if conversation is None:
                return None
            return conversation.status

    async def list_outbox(
        self, tenant: TenantContext, *, kind: str | None = None
    ) -> tuple[HandoffOutbox, ...]:
        async with self._lock:
            items = [
                item
                for item in self._outbox
                if item.tenant_id == tenant.tenant_id
                and (kind is None or item.kind == kind)
            ]
            return tuple(items)

    async def count_cases(self, tenant: TenantContext) -> int:
        async with self._lock:
            return sum(1 for key in self._cases if key[0] == tenant.tenant_id)

    async def create_with_ownership(
        self,
        tenant: TenantContext,
        case: HandoffCase,
        outbox: HandoffOutbox,
        conversation_id: UUID,
    ) -> HandoffCase:
        async with self._lock:
            if case.tenant_id != tenant.tenant_id:
                raise HandoffError("not_found", "Resource not found")
            key = (tenant.tenant_id, case.business_key)
            if key in self._by_key:
                raise HandoffError("conflict", "Handoff already exists.")
            conversation = self._conversations.get((tenant.tenant_id, conversation_id))
            if conversation is None:
                raise HandoffError("not_found", "Resource not found")
            self._conversations[(tenant.tenant_id, conversation_id)] = Conversation(
                id=conversation.id,
                tenant_id=conversation.tenant_id,
                channel_integration_id=conversation.channel_integration_id,
                status="human_owned",
                last_message_at=conversation.last_message_at,
                lock_version=conversation.lock_version + 1,
            )
            self._cases[(tenant.tenant_id, case.id)] = case
            self._by_key[key] = case.id
            self._outbox.append(outbox)
            return case
