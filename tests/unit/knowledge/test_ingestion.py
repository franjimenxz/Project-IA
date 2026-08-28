from uuid import UUID

import pytest

from ia_mcp.knowledge.adapters.object_store import InMemoryObjectStore
from ia_mcp.knowledge.models import DocumentSource
from ia_mcp.knowledge.ports import KnowledgeError
from ia_mcp.knowledge.service import KnowledgeService
from ia_mcp.tenancy.models import TenantContext
from tests.unit.knowledge.fakes import FakeChunker, FakeEmbedding, FakeParser

TENANT_A = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
TENANT_A_CTX = TenantContext(
    tenant_id=TENANT_A,
    tenant_slug="tenant-a",
    config_version=1,
    correlation_id=UUID("33333333-3333-3333-3333-333333333333"),
)


class _MemoryRepo:
    def __init__(self) -> None:
        self.saved: list[object] = []
        self.failed: list[object] = []

    async def save_draft(self, tenant: TenantContext, record: object) -> None:
        self.saved.append((tenant.tenant_id, record))

    async def mark_failed(self, tenant: TenantContext, record: object) -> None:
        self.failed.append((tenant.tenant_id, record))

    async def publish(self, tenant: TenantContext, document_id: UUID, version: int) -> None:
        del tenant, document_id, version

    async def search_published(self, tenant: TenantContext, limit: int) -> tuple[object, ...]:
        del tenant, limit
        return ()


@pytest.mark.anyio
async def test_parser_fault_marks_failed_without_chunks() -> None:
    repo = _MemoryRepo()
    service = KnowledgeService(
        repository=repo,
        parser=FakeParser(),
        chunker=FakeChunker(),
        embeddings=FakeEmbedding(),
        object_store=InMemoryObjectStore(),
    )
    result = await service.ingest(
        TENANT_A_CTX, DocumentSource(filename="bad.pdf", payload=b"FAULT")
    )
    assert result.status == "failed"
    assert result.error_code == "parse_failed"
    assert repo.saved == []
    assert len(repo.failed) == 1


@pytest.mark.anyio
async def test_object_store_rejects_cross_tenant_get() -> None:
    store = InMemoryObjectStore()
    key = await store.put(TENANT_A_CTX, "doc.pdf", b"hello")
    other = TenantContext(
        tenant_id=UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"),
        tenant_slug="tenant-b",
        config_version=1,
        correlation_id=UUID("44444444-4444-4444-4444-444444444444"),
    )
    with pytest.raises(KnowledgeError) as caught:
        await store.get(other, key)
    assert caught.value.code == "tenant_isolation_violation"
