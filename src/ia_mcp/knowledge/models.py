from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from ia_mcp.tenancy.models import TenantContext


class DocumentStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class DocumentSource:
    filename: str
    payload: bytes
    mime_type: str = "application/pdf"


@dataclass(frozen=True, slots=True)
class ParsedPage:
    page: int
    text: str


@dataclass(frozen=True, slots=True)
class PreparedChunk:
    page: int
    position: int
    text: str


@dataclass(frozen=True, slots=True)
class KnowledgeQuery:
    text: str
    limit: int = 5


@dataclass(frozen=True, slots=True)
class KnowledgeHit:
    tenant_id: UUID
    source_id: str
    text: str
    score: float
    document_id: UUID
    document_version: int
    page: int


@dataclass(frozen=True, slots=True)
class IngestionResult:
    document_id: UUID
    version: int
    status: DocumentStatus
    checksum: str
    error_code: str | None = None


@dataclass(frozen=True, slots=True)
class StoredChunk:
    tenant_id: UUID
    chunk_id: UUID
    document_id: UUID
    version: int
    page: int
    position: int
    text: str
    embedding: tuple[float, ...]
    source_id: str


@dataclass(frozen=True, slots=True)
class DraftRecord:
    tenant: TenantContext
    document_id: UUID
    version: int
    filename: str
    checksum: str
    object_key: str
    mime_type: str
    chunks: tuple[StoredChunk, ...]


@dataclass(frozen=True, slots=True)
class FailedRecord:
    tenant: TenantContext
    document_id: UUID
    version: int
    filename: str
    checksum: str
    object_key: str | None
    error_code: str
