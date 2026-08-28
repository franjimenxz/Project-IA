from datetime import UTC, datetime
from uuid import UUID

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
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from ia_mcp.knowledge.models import DraftRecord, FailedRecord, StoredChunk
from ia_mcp.knowledge.ports import KnowledgeError
from ia_mcp.tenancy.models import TenantContext

metadata = MetaData()

knowledge_document_table = Table(
    "knowledge_document",
    metadata,
    Column("tenant_id", PGUUID(as_uuid=True), nullable=False),
    Column("id", PGUUID(as_uuid=True), nullable=False),
    Column("logical_name", String(255), nullable=False),
    Column("object_key", String(512), nullable=False),
    Column("mime_type", String(128), nullable=False),
    Column("checksum", String(64), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    PrimaryKeyConstraint("tenant_id", "id"),
    UniqueConstraint("tenant_id", "checksum"),
    UniqueConstraint("tenant_id", "id"),
)

knowledge_document_version_table = Table(
    "knowledge_document_version",
    metadata,
    Column("tenant_id", PGUUID(as_uuid=True), nullable=False),
    Column("document_id", PGUUID(as_uuid=True), nullable=False),
    Column("version", Integer, nullable=False),
    Column("status", String(32), nullable=False),
    Column("error_code", String(64), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("published_at", DateTime(timezone=True), nullable=True),
    PrimaryKeyConstraint("tenant_id", "document_id", "version"),
    ForeignKeyConstraint(
        ["tenant_id", "document_id"],
        ["knowledge_document.tenant_id", "knowledge_document.id"],
    ),
)

knowledge_chunk_table = Table(
    "knowledge_chunk",
    metadata,
    Column("tenant_id", PGUUID(as_uuid=True), nullable=False),
    Column("id", PGUUID(as_uuid=True), nullable=False),
    Column("document_id", PGUUID(as_uuid=True), nullable=False),
    Column("version", Integer, nullable=False),
    Column("page", Integer, nullable=False),
    Column("position", Integer, nullable=False),
    Column("text", String, nullable=False),
    Column("embedding", JSONB, nullable=False),
    Column("source_id", String(255), nullable=False),
    Column("token_count", Integer, nullable=False),
    PrimaryKeyConstraint("tenant_id", "id"),
    UniqueConstraint("tenant_id", "source_id"),
    ForeignKeyConstraint(
        ["tenant_id", "document_id", "version"],
        [
            "knowledge_document_version.tenant_id",
            "knowledge_document_version.document_id",
            "knowledge_document_version.version",
        ],
    ),
)


def _now() -> datetime:
    return datetime.now(UTC)


class SqlAlchemyKnowledgeRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self._session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def save_draft(self, tenant: TenantContext, record: DraftRecord) -> None:
        async with self._session_factory() as session, session.begin():
            await session.execute(
                knowledge_document_table.insert().values(
                    tenant_id=tenant.tenant_id,
                    id=record.document_id,
                    logical_name=record.filename,
                    object_key=record.object_key,
                    mime_type=record.mime_type,
                    checksum=record.checksum,
                    created_at=_now(),
                )
            )
            await session.execute(
                knowledge_document_version_table.insert().values(
                    tenant_id=tenant.tenant_id,
                    document_id=record.document_id,
                    version=record.version,
                    status="draft",
                    error_code=None,
                    created_at=_now(),
                    published_at=None,
                )
            )
            for chunk in record.chunks:
                await session.execute(
                    knowledge_chunk_table.insert().values(
                        tenant_id=tenant.tenant_id,
                        id=chunk.chunk_id,
                        document_id=record.document_id,
                        version=record.version,
                        page=chunk.page,
                        position=chunk.position,
                        text=chunk.text,
                        embedding=list(chunk.embedding),
                        source_id=chunk.source_id,
                        token_count=max(1, len(chunk.text.split())),
                    )
                )

    async def mark_failed(self, tenant: TenantContext, record: FailedRecord) -> None:
        async with self._session_factory() as session, session.begin():
            await session.execute(
                knowledge_document_table.insert().values(
                    tenant_id=tenant.tenant_id,
                    id=record.document_id,
                    logical_name=record.filename,
                    object_key=record.object_key or f"{tenant.tenant_id}/failed/{record.document_id}",
                    mime_type="application/pdf",
                    checksum=record.checksum,
                    created_at=_now(),
                )
            )
            await session.execute(
                knowledge_document_version_table.insert().values(
                    tenant_id=tenant.tenant_id,
                    document_id=record.document_id,
                    version=record.version,
                    status="failed",
                    error_code=record.error_code,
                    created_at=_now(),
                    published_at=None,
                )
            )

    async def publish(
        self, tenant: TenantContext, document_id: UUID, version: int
    ) -> None:
        async with self._session_factory() as session, session.begin():
            row = (
                await session.execute(
                    select(knowledge_document_version_table.c.version).where(
                        knowledge_document_version_table.c.tenant_id == tenant.tenant_id,
                        knowledge_document_version_table.c.document_id == document_id,
                        knowledge_document_version_table.c.version == version,
                    )
                )
            ).first()
            if row is None:
                raise KnowledgeError("not_found", "Document version is not available.")
            await session.execute(
                knowledge_document_version_table.update()
                .where(
                    knowledge_document_version_table.c.tenant_id == tenant.tenant_id,
                    knowledge_document_version_table.c.document_id == document_id,
                    knowledge_document_version_table.c.status == "published",
                )
                .values(status="superseded")
            )
            await session.execute(
                knowledge_document_version_table.update()
                .where(
                    knowledge_document_version_table.c.tenant_id == tenant.tenant_id,
                    knowledge_document_version_table.c.document_id == document_id,
                    knowledge_document_version_table.c.version == version,
                )
                .values(status="published", published_at=_now())
            )

    async def search_published(
        self, tenant: TenantContext, limit: int
    ) -> tuple[StoredChunk, ...]:
        del limit
        async with self._session_factory() as session:
            rows = (
                await session.execute(
                    select(knowledge_chunk_table)
                    .join(
                        knowledge_document_version_table,
                        (
                            knowledge_chunk_table.c.tenant_id
                            == knowledge_document_version_table.c.tenant_id
                        )
                        & (
                            knowledge_chunk_table.c.document_id
                            == knowledge_document_version_table.c.document_id
                        )
                        & (
                            knowledge_chunk_table.c.version
                            == knowledge_document_version_table.c.version
                        ),
                    )
                    .where(
                        knowledge_chunk_table.c.tenant_id == tenant.tenant_id,
                        knowledge_document_version_table.c.status == "published",
                    )
                )
            ).mappings().all()
        chunks: list[StoredChunk] = []
        for row in rows:
            if row["tenant_id"] != tenant.tenant_id:
                raise KnowledgeError(
                    "tenant_isolation_violation",
                    "Knowledge chunk does not belong to this tenant.",
                )
            embedding = row["embedding"]
            chunks.append(
                StoredChunk(
                    tenant_id=row["tenant_id"],
                    chunk_id=row["id"],
                    document_id=row["document_id"],
                    version=row["version"],
                    page=row["page"],
                    position=row["position"],
                    text=row["text"],
                    embedding=tuple(float(value) for value in embedding),
                    source_id=row["source_id"],
                )
            )
        return tuple(chunks)
