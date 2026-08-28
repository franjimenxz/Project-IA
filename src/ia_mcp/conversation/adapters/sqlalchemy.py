from datetime import UTC, datetime
from hashlib import sha256
from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKeyConstraint,
    Integer,
    MetaData,
    PrimaryKeyConstraint,
    String,
    Table,
    UniqueConstraint,
    select,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from ia_mcp.conversation.models import (
    ContentType,
    Conversation,
    ConversationStatus,
    InboundMessage,
    Message,
    MessageDirection,
    ReceivedMessage,
    SessionState,
)
from ia_mcp.conversation.ports import ConversationError
from ia_mcp.tenancy.models import TenantContext

metadata = MetaData()

conversation_table = Table(
    "conversation",
    metadata,
    Column("id", PGUUID(as_uuid=True), nullable=False),
    Column("tenant_id", PGUUID(as_uuid=True), nullable=False),
    Column("channel_integration_id", PGUUID(as_uuid=True), nullable=False),
    Column("external_user_ref", String(64), nullable=False),
    Column("status", String(32), nullable=False),
    Column("last_message_at", DateTime(timezone=True), nullable=False),
    Column("lock_version", Integer, nullable=False),
    PrimaryKeyConstraint("tenant_id", "id"),
    UniqueConstraint(
        "tenant_id",
        "channel_integration_id",
        "external_user_ref",
        name="uq_conversation_tenant_channel_user",
    ),
)

message_table = Table(
    "message",
    metadata,
    Column("id", PGUUID(as_uuid=True), nullable=False),
    Column("tenant_id", PGUUID(as_uuid=True), nullable=False),
    Column("conversation_id", PGUUID(as_uuid=True), nullable=False),
    Column("channel_integration_id", PGUUID(as_uuid=True), nullable=False),
    Column("direction", String(16), nullable=False),
    Column("external_message_id", String(255), nullable=False),
    Column("content", String, nullable=False),
    Column("content_type", String(32), nullable=False),
    Column("occurred_at", DateTime(timezone=True), nullable=False),
    Column("received_at", DateTime(timezone=True), nullable=False),
    Column("dedupe_hash", String(64), nullable=False),
    PrimaryKeyConstraint("tenant_id", "id"),
    UniqueConstraint(
        "tenant_id",
        "channel_integration_id",
        "external_message_id",
        name="uq_message_tenant_channel_external",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "conversation_id"],
        ["conversation.tenant_id", "conversation.id"],
    ),
)

session_state_table = Table(
    "session_state",
    metadata,
    Column("tenant_id", PGUUID(as_uuid=True), nullable=False),
    Column("conversation_id", PGUUID(as_uuid=True), nullable=False),
    Column("active_skill", String(64), nullable=True),
    Column("active_workflow_id", PGUUID(as_uuid=True), nullable=True),
    Column("compacted_memory", JSONB, nullable=True),
    Column("state_version", Integer, nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=True),
    PrimaryKeyConstraint("tenant_id", "conversation_id"),
    ForeignKeyConstraint(
        ["tenant_id", "conversation_id"],
        ["conversation.tenant_id", "conversation.id"],
    ),
)


def _now() -> datetime:
    return datetime.now(UTC)


def _user_ref_token(
    tenant_id: UUID, channel_integration_id: UUID, external_user_id: str
) -> str:
    material = f"{tenant_id}:{channel_integration_id}:{external_user_id}"
    return sha256(material.encode("utf-8")).hexdigest()


def _dedupe_hash(channel_integration_id: UUID, external_message_id: str) -> str:
    material = f"{channel_integration_id}:{external_message_id}"
    return sha256(material.encode("utf-8")).hexdigest()


def _conversation_from_row(row: Any) -> Conversation:
    return Conversation(
        id=row["id"],
        tenant_id=row["tenant_id"],
        channel_integration_id=row["channel_integration_id"],
        status=cast(ConversationStatus, row["status"]),
        last_message_at=row["last_message_at"],
        lock_version=int(row["lock_version"]),
    )


def _message_from_row(row: Any) -> Message:
    return Message(
        id=row["id"],
        tenant_id=row["tenant_id"],
        conversation_id=row["conversation_id"],
        direction=cast(MessageDirection, row["direction"]),
        external_message_id=row["external_message_id"],
        content_type=cast(ContentType, row["content_type"]),
        occurred_at=row["occurred_at"],
        received_at=row["received_at"],
        dedupe_hash=row["dedupe_hash"],
    )


def _session_from_row(row: Any) -> SessionState:
    return SessionState(
        tenant_id=row["tenant_id"],
        conversation_id=row["conversation_id"],
        active_skill=row["active_skill"],
        active_workflow_id=row["active_workflow_id"],
        state_version=int(row["state_version"]),
        expires_at=row["expires_at"],
    )


class SqlAlchemyConversationRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self._session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def receive(
        self, tenant: TenantContext, message: InboundMessage
    ) -> ReceivedMessage:
        try:
            async with self._session_factory() as session, session.begin():
                return await self._receive(session, tenant, message)
        except IntegrityError as exc:
            raise ConversationError(
                "not_found", "Channel integration is not available."
            ) from exc

    async def get(
        self, tenant: TenantContext, conversation_id: UUID
    ) -> Conversation | None:
        async with self._session_factory() as session:
            row = (
                (
                    await session.execute(
                        select(conversation_table).where(
                            conversation_table.c.tenant_id == tenant.tenant_id,
                            conversation_table.c.id == conversation_id,
                        )
                    )
                )
                .mappings()
                .first()
            )
            if row is None:
                return None
            return _conversation_from_row(row)

    async def get_session(
        self, tenant: TenantContext, conversation_id: UUID
    ) -> SessionState | None:
        async with self._session_factory() as session:
            return await self._load_session(session, tenant.tenant_id, conversation_id)

    async def get_message(
        self, tenant: TenantContext, message_id: UUID
    ) -> Message | None:
        async with self._session_factory() as session:
            row = (
                (
                    await session.execute(
                        select(message_table).where(
                            message_table.c.tenant_id == tenant.tenant_id,
                            message_table.c.id == message_id,
                        )
                    )
                )
                .mappings()
                .first()
            )
            if row is None:
                return None
            return _message_from_row(row)

    async def cas_update_session(
        self,
        tenant: TenantContext,
        conversation_id: UUID,
        expected_version: int,
        *,
        active_skill: str | None,
    ) -> SessionState:
        async with self._session_factory() as session, session.begin():
            row = (
                (
                    await session.execute(
                        session_state_table.update()
                        .where(
                            session_state_table.c.tenant_id == tenant.tenant_id,
                            session_state_table.c.conversation_id == conversation_id,
                            session_state_table.c.state_version == expected_version,
                        )
                        .values(
                            active_skill=active_skill,
                            state_version=expected_version + 1,
                        )
                        .returning(session_state_table)
                    )
                )
                .mappings()
                .first()
            )
            if row is not None:
                return _session_from_row(row)
            existing = await self._load_session(
                session, tenant.tenant_id, conversation_id
            )
            if existing is None:
                raise ConversationError("not_found", "Resource not found")
            raise ConversationError(
                "conflict", "Session state was updated concurrently."
            )

    async def _receive(
        self,
        session: AsyncSession,
        tenant: TenantContext,
        message: InboundMessage,
    ) -> ReceivedMessage:
        now = _now()
        user_ref = _user_ref_token(
            tenant.tenant_id,
            message.channel_integration_id,
            message.external_user_id,
        )
        digest = _dedupe_hash(
            message.channel_integration_id, message.external_message_id
        )
        conversation = await self._upsert_conversation(
            session, tenant, message, user_ref, now
        )
        existing_message = await self._load_message_by_external(
            session,
            tenant.tenant_id,
            message.channel_integration_id,
            message.external_message_id,
        )
        if existing_message is not None:
            session_state = await self._require_session(
                session, tenant.tenant_id, conversation.id
            )
            return ReceivedMessage(
                conversation=conversation,
                message=existing_message,
                session=session_state,
                duplicate=True,
            )
        stored = await self._insert_message(
            session, tenant, conversation.id, message, digest, now
        )
        if not stored:
            stored_message = await self._load_message_by_external(
                session,
                tenant.tenant_id,
                message.channel_integration_id,
                message.external_message_id,
            )
            if stored_message is None:
                raise ConversationError("not_found", "Resource not found")
            session_state = await self._require_session(
                session, tenant.tenant_id, conversation.id
            )
            return ReceivedMessage(
                conversation=conversation,
                message=stored_message,
                session=session_state,
                duplicate=True,
            )
        conversation = await self._touch_conversation(
            session, tenant.tenant_id, conversation.id, now
        )
        session_state = await self._ensure_session(
            session, tenant.tenant_id, conversation.id
        )
        return ReceivedMessage(
            conversation=conversation,
            message=stored,
            session=session_state,
            duplicate=False,
        )

    async def _upsert_conversation(
        self,
        session: AsyncSession,
        tenant: TenantContext,
        message: InboundMessage,
        user_ref: str,
        now: datetime,
    ) -> Conversation:
        inserted = (
            (
                await session.execute(
                    pg_insert(conversation_table)
                    .values(
                        id=uuid4(),
                        tenant_id=tenant.tenant_id,
                        channel_integration_id=message.channel_integration_id,
                        external_user_ref=user_ref,
                        status="bot_owned",
                        last_message_at=now,
                        lock_version=1,
                    )
                    .on_conflict_do_nothing(
                        constraint="uq_conversation_tenant_channel_user"
                    )
                    .returning(conversation_table)
                )
            )
            .mappings()
            .first()
        )
        if inserted is not None:
            return _conversation_from_row(inserted)
        row = (
            (
                await session.execute(
                    select(conversation_table)
                    .where(
                        conversation_table.c.tenant_id == tenant.tenant_id,
                        conversation_table.c.channel_integration_id
                        == message.channel_integration_id,
                        conversation_table.c.external_user_ref == user_ref,
                    )
                    .with_for_update()
                )
            )
            .mappings()
            .first()
        )
        if row is None:
            raise ConversationError("not_found", "Resource not found")
        return _conversation_from_row(row)

    async def _insert_message(
        self,
        session: AsyncSession,
        tenant: TenantContext,
        conversation_id: UUID,
        message: InboundMessage,
        digest: str,
        now: datetime,
    ) -> Message | None:
        row = (
            (
                await session.execute(
                    pg_insert(message_table)
                    .values(
                        id=uuid4(),
                        tenant_id=tenant.tenant_id,
                        conversation_id=conversation_id,
                        channel_integration_id=message.channel_integration_id,
                        direction="inbound",
                        external_message_id=message.external_message_id,
                        content=message.text,
                        content_type=message.content_type,
                        occurred_at=message.occurred_at,
                        received_at=now,
                        dedupe_hash=digest,
                    )
                    .on_conflict_do_nothing(
                        constraint="uq_message_tenant_channel_external"
                    )
                    .returning(message_table)
                )
            )
            .mappings()
            .first()
        )
        if row is None:
            return None
        return _message_from_row(row)

    async def _touch_conversation(
        self,
        session: AsyncSession,
        tenant_id: UUID,
        conversation_id: UUID,
        now: datetime,
    ) -> Conversation:
        row = (
            (
                await session.execute(
                    conversation_table.update()
                    .where(
                        conversation_table.c.tenant_id == tenant_id,
                        conversation_table.c.id == conversation_id,
                    )
                    .values(
                        last_message_at=now,
                        lock_version=conversation_table.c.lock_version + 1,
                    )
                    .returning(conversation_table)
                )
            )
            .mappings()
            .first()
        )
        if row is None:
            raise ConversationError("not_found", "Resource not found")
        return _conversation_from_row(row)

    async def _ensure_session(
        self, session: AsyncSession, tenant_id: UUID, conversation_id: UUID
    ) -> SessionState:
        inserted = (
            (
                await session.execute(
                    pg_insert(session_state_table)
                    .values(
                        tenant_id=tenant_id,
                        conversation_id=conversation_id,
                        active_skill=None,
                        active_workflow_id=None,
                        compacted_memory=None,
                        state_version=1,
                        expires_at=None,
                    )
                    .on_conflict_do_nothing(
                        index_elements=["tenant_id", "conversation_id"]
                    )
                    .returning(session_state_table)
                )
            )
            .mappings()
            .first()
        )
        if inserted is not None:
            return _session_from_row(inserted)
        return await self._require_session(session, tenant_id, conversation_id)

    async def _require_session(
        self, session: AsyncSession, tenant_id: UUID, conversation_id: UUID
    ) -> SessionState:
        loaded = await self._load_session(session, tenant_id, conversation_id)
        if loaded is None:
            raise ConversationError("not_found", "Resource not found")
        return loaded

    async def _load_session(
        self, session: AsyncSession, tenant_id: UUID, conversation_id: UUID
    ) -> SessionState | None:
        row = (
            (
                await session.execute(
                    select(session_state_table).where(
                        session_state_table.c.tenant_id == tenant_id,
                        session_state_table.c.conversation_id == conversation_id,
                    )
                )
            )
            .mappings()
            .first()
        )
        if row is None:
            return None
        return _session_from_row(row)

    async def _load_message_by_external(
        self,
        session: AsyncSession,
        tenant_id: UUID,
        channel_integration_id: UUID,
        external_message_id: str,
    ) -> Message | None:
        row = (
            (
                await session.execute(
                    select(message_table).where(
                        message_table.c.tenant_id == tenant_id,
                        message_table.c.channel_integration_id
                        == channel_integration_id,
                        message_table.c.external_message_id == external_message_id,
                    )
                )
            )
            .mappings()
            .first()
        )
        if row is None:
            return None
        return _message_from_row(row)
