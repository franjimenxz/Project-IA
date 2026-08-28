from typing import Protocol
from uuid import UUID

from ia_mcp.knowledge.models import (
    DocumentSource,
    DraftRecord,
    FailedRecord,
    IngestionResult,
    KnowledgeHit,
    KnowledgeQuery,
    ParsedPage,
    PreparedChunk,
    StoredChunk,
)
from ia_mcp.tenancy.models import TenantContext


class ParseError(Exception):
    def __init__(self, code: str, safe_message: str) -> None:
        self.code = code
        self.safe_message = safe_message
        super().__init__(safe_message)


class KnowledgeError(Exception):
    def __init__(self, code: str, safe_message: str) -> None:
        self.code = code
        self.safe_message = safe_message
        super().__init__(safe_message)


class Parser(Protocol):
    async def parse(self, payload: bytes) -> tuple[ParsedPage, ...]: ...


class Chunker(Protocol):
    async def chunk(self, pages: tuple[ParsedPage, ...]) -> tuple[PreparedChunk, ...]: ...


class EmbeddingPort(Protocol):
    async def embed(self, texts: tuple[str, ...]) -> tuple[tuple[float, ...], ...]: ...


class ObjectStore(Protocol):
    async def put(self, tenant: TenantContext, key: str, payload: bytes) -> str: ...

    async def get(self, tenant: TenantContext, key: str) -> bytes | None: ...


class KnowledgeRepository(Protocol):
    async def save_draft(self, tenant: TenantContext, record: DraftRecord) -> None: ...

    async def mark_failed(self, tenant: TenantContext, record: FailedRecord) -> None: ...

    async def publish(
        self, tenant: TenantContext, document_id: UUID, version: int
    ) -> None: ...

    async def search_published(
        self, tenant: TenantContext, limit: int
    ) -> tuple[StoredChunk, ...]: ...


class KnowledgeIngestor(Protocol):
    async def ingest(
        self, tenant: TenantContext, document: DocumentSource
    ) -> IngestionResult: ...

    async def publish(
        self, tenant: TenantContext, document_id: UUID, version: int
    ) -> None: ...


class KnowledgeServicePort(Protocol):
    async def search(
        self, tenant: TenantContext, query: KnowledgeQuery
    ) -> tuple[KnowledgeHit, ...]: ...
