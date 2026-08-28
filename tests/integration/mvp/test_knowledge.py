from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import command
from ia_mcp.configuration.adapters.sqlalchemy import tenant_table
from ia_mcp.knowledge.adapters.object_store import InMemoryObjectStore
from ia_mcp.knowledge.adapters.sqlalchemy import SqlAlchemyKnowledgeRepository
from ia_mcp.knowledge.models import DocumentSource, KnowledgeQuery
from ia_mcp.knowledge.service import KnowledgeService
from ia_mcp.tenancy.models import TenantContext
from tests.unit.knowledge.fakes import (
    DownEmbedding,
    FakeChunker,
    FakeEmbedding,
    FakeParser,
)

ROOT = Path(__file__).resolve().parents[3]
DATABASE_URL = "postgresql+psycopg://francojimenez@127.0.0.1:5432/ia_mcp_p02_t03"

TENANT_A = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
TENANT_B = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
TENANT_A_CTX = TenantContext(
    tenant_id=TENANT_A,
    tenant_slug="tenant-a",
    config_version=1,
    correlation_id=UUID("33333333-3333-3333-3333-333333333333"),
)
TENANT_B_CTX = TenantContext(
    tenant_id=TENANT_B,
    tenant_slug="tenant-b",
    config_version=1,
    correlation_id=UUID("44444444-4444-4444-4444-444444444444"),
)


def _reset_schema() -> None:
    engine = create_engine(DATABASE_URL)
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))
    engine.dispose()
    alembic_cfg = Config(str(ROOT / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(ROOT / "alembic"))
    alembic_cfg.set_main_option("sqlalchemy.url", DATABASE_URL)
    command.upgrade(alembic_cfg, "head")


def _seed_tenants() -> None:
    engine = create_engine(DATABASE_URL)
    now = datetime.now(UTC)
    with engine.begin() as connection:
        connection.execute(
            tenant_table.insert(),
            [
                {
                    "id": TENANT_A,
                    "slug": "tenant-a",
                    "status": "active",
                    "active_config_version": None,
                    "created_at": now,
                    "updated_at": now,
                },
                {
                    "id": TENANT_B,
                    "slug": "tenant-b",
                    "status": "active",
                    "active_config_version": None,
                    "created_at": now,
                    "updated_at": now,
                },
            ],
        )
    engine.dispose()


def _service(engine, embeddings=None) -> KnowledgeService:
    return KnowledgeService(
        repository=SqlAlchemyKnowledgeRepository(engine),
        parser=FakeParser(),
        chunker=FakeChunker(),
        embeddings=embeddings or FakeEmbedding(),
        object_store=InMemoryObjectStore(),
    )


@pytest.fixture
async def service() -> AsyncIterator[KnowledgeService]:
    _reset_schema()
    _seed_tenants()
    engine = create_async_engine(DATABASE_URL)
    try:
        yield _service(engine)
    finally:
        await engine.dispose()


@pytest.mark.anyio
@pytest.mark.integration
async def test_search_under_a_returns_only_a_canary_hits(
    service: KnowledgeService,
) -> None:
    draft_a = await service.ingest(
        TENANT_A_CTX,
        DocumentSource(filename="a.pdf", payload=b"canary-a clinic hours eight to sixteen"),
    )
    draft_b = await service.ingest(
        TENANT_B_CTX,
        DocumentSource(filename="b.pdf", payload=b"canary-b exclusive tenant b secret"),
    )
    await service.publish(TENANT_A_CTX, draft_a.document_id, draft_a.version)
    await service.publish(TENANT_B_CTX, draft_b.document_id, draft_b.version)
    hits = await service.search(TENANT_A_CTX, KnowledgeQuery(text="canary-a hours", limit=5))
    assert hits
    assert all(hit.tenant_id == TENANT_A for hit in hits)
    assert all("canary-b" not in hit.text for hit in hits)
    assert any("canary-a" in hit.text for hit in hits)
    assert hits[0].page == 1
    assert hits[0].document_version == 1
    assert hits[0].source_id


@pytest.mark.anyio
@pytest.mark.integration
async def test_draft_and_failed_documents_are_excluded_from_search(
    service: KnowledgeService,
) -> None:
    draft = await service.ingest(
        TENANT_A_CTX,
        DocumentSource(filename="draft.pdf", payload=b"canary-a draft only"),
    )
    failed = await service.ingest(
        TENANT_A_CTX, DocumentSource(filename="bad.pdf", payload=b"FAULT")
    )
    published = await service.ingest(
        TENANT_A_CTX,
        DocumentSource(filename="live.pdf", payload=b"canary-a published hours"),
    )
    await service.publish(TENANT_A_CTX, published.document_id, published.version)
    hits = await service.search(TENANT_A_CTX, KnowledgeQuery(text="canary-a", limit=10))
    texts = [hit.text for hit in hits]
    assert any("published" in text for text in texts)
    assert all("draft only" not in text for text in texts)
    assert failed.status == "failed"
    assert draft.status == "draft"


@pytest.mark.anyio
@pytest.mark.integration
async def test_parser_fault_does_not_leave_partial_chunks(
    service: KnowledgeService,
) -> None:
    result = await service.ingest(
        TENANT_A_CTX, DocumentSource(filename="bad.pdf", payload=b"FAULT")
    )
    assert result.status == "failed"
    hits = await service.search(TENANT_A_CTX, KnowledgeQuery(text="anything", limit=10))
    assert hits == ()


@pytest.mark.anyio
@pytest.mark.integration
async def test_retrieval_down_returns_no_hits_without_inventing(
    service: KnowledgeService,
) -> None:
    draft = await service.ingest(
        TENANT_A_CTX,
        DocumentSource(filename="a.pdf", payload=b"canary-a clinic hours"),
    )
    await service.publish(TENANT_A_CTX, draft.document_id, draft.version)
    engine = create_async_engine(DATABASE_URL)
    try:
        down = _service(engine, embeddings=DownEmbedding())
        hits = await down.search(TENANT_A_CTX, KnowledgeQuery(text="canary-a", limit=5))
        assert hits == ()
    finally:
        await engine.dispose()


@pytest.mark.anyio
@pytest.mark.integration
async def test_tenants_receive_distinct_corpus_hits(
    service: KnowledgeService,
) -> None:
    a = await service.ingest(
        TENANT_A_CTX, DocumentSource(filename="a.pdf", payload=b"canary-a hours")
    )
    b = await service.ingest(
        TENANT_B_CTX, DocumentSource(filename="b.pdf", payload=b"canary-b specialty")
    )
    await service.publish(TENANT_A_CTX, a.document_id, a.version)
    await service.publish(TENANT_B_CTX, b.document_id, b.version)
    hits_a = await service.search(TENANT_A_CTX, KnowledgeQuery(text="canary-a", limit=5))
    hits_b = await service.search(TENANT_B_CTX, KnowledgeQuery(text="canary-b", limit=5))
    assert any("canary-a" in hit.text for hit in hits_a)
    assert any("canary-b" in hit.text for hit in hits_b)
    assert all(hit.tenant_id == TENANT_A for hit in hits_a)
    assert all(hit.tenant_id == TENANT_B for hit in hits_b)
