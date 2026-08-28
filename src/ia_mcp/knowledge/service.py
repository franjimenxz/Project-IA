from hashlib import sha256
from uuid import UUID, uuid4

from ia_mcp.knowledge.models import (
    DocumentSource,
    DocumentStatus,
    DraftRecord,
    FailedRecord,
    IngestionResult,
    KnowledgeHit,
    KnowledgeQuery,
    StoredChunk,
)
from ia_mcp.knowledge.ports import (
    Chunker,
    EmbeddingPort,
    KnowledgeError,
    KnowledgeRepository,
    ObjectStore,
    ParseError,
    Parser,
)
from ia_mcp.tenancy.models import TenantContext


def _cosine(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    return float(dot)


class KnowledgeService:
    def __init__(
        self,
        *,
        repository: KnowledgeRepository,
        parser: Parser,
        chunker: Chunker,
        embeddings: EmbeddingPort,
        object_store: ObjectStore,
    ) -> None:
        self._repository = repository
        self._parser = parser
        self._chunker = chunker
        self._embeddings = embeddings
        self._object_store = object_store

    async def ingest(
        self, tenant: TenantContext, document: DocumentSource
    ) -> IngestionResult:
        checksum = sha256(document.payload).hexdigest()
        document_id = uuid4()
        version = 1
        object_key: str | None = None
        try:
            object_key = await self._object_store.put(
                tenant, f"{document_id}/{document.filename}", document.payload
            )
            pages = await self._parser.parse(document.payload)
            prepared = await self._chunker.chunk(pages)
            vectors = await self._embeddings.embed(tuple(item.text for item in prepared))
            chunks = tuple(
                StoredChunk(
                    tenant_id=tenant.tenant_id,
                    chunk_id=uuid4(),
                    document_id=document_id,
                    version=version,
                    page=item.page,
                    position=item.position,
                    text=item.text,
                    embedding=vector,
                    source_id=f"{document_id}:v{version}:p{item.page}:{item.position}",
                )
                for item, vector in zip(prepared, vectors, strict=True)
            )
            await self._repository.save_draft(
                tenant,
                DraftRecord(
                    tenant=tenant,
                    document_id=document_id,
                    version=version,
                    filename=document.filename,
                    checksum=checksum,
                    object_key=object_key,
                    mime_type=document.mime_type,
                    chunks=chunks,
                ),
            )
            return IngestionResult(
                document_id=document_id,
                version=version,
                status=DocumentStatus.DRAFT,
                checksum=checksum,
            )
        except ParseError as error:
            await self._repository.mark_failed(
                tenant,
                FailedRecord(
                    tenant=tenant,
                    document_id=document_id,
                    version=version,
                    filename=document.filename,
                    checksum=checksum,
                    object_key=object_key,
                    error_code=error.code,
                ),
            )
            return IngestionResult(
                document_id=document_id,
                version=version,
                status=DocumentStatus.FAILED,
                checksum=checksum,
                error_code=error.code,
            )

    async def publish(
        self, tenant: TenantContext, document_id: UUID, version: int
    ) -> None:
        await self._repository.publish(tenant, document_id, version)

    async def search(
        self, tenant: TenantContext, query: KnowledgeQuery
    ) -> tuple[KnowledgeHit, ...]:
        try:
            query_vector = (await self._embeddings.embed((query.text,)))[0]
        except RuntimeError:
            return ()
        candidates = await self._repository.search_published(tenant, query.limit * 4)
        hits: list[KnowledgeHit] = []
        for chunk in candidates:
            if chunk.tenant_id != tenant.tenant_id:
                raise KnowledgeError(
                    "tenant_isolation_violation",
                    "Knowledge chunk does not belong to this tenant.",
                )
            score = _cosine(query_vector, chunk.embedding)
            hits.append(
                KnowledgeHit(
                    tenant_id=chunk.tenant_id,
                    source_id=chunk.source_id,
                    text=chunk.text,
                    score=score,
                    document_id=chunk.document_id,
                    document_version=chunk.version,
                    page=chunk.page,
                )
            )
        hits.sort(key=lambda item: item.score, reverse=True)
        return tuple(hits[: query.limit])
