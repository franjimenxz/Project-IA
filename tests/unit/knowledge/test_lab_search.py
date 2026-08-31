from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

import pytest

from ia_mcp.knowledge.lab_search import LabKnowledgeSearch
from ia_mcp.knowledge.models import KnowledgeQuery
from ia_mcp.tenancy.models import TenantContext

TENANT_A = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
CORR = UUID("33333333-3333-3333-3333-333333333333")


def tenant_a() -> TenantContext:
    return TenantContext(
        tenant_id=TENANT_A,
        tenant_slug="tenant-a",
        config_version=1,
        correlation_id=CORR,
    )


def write_txt(root: Path, slug: str, filename: str, text: str) -> None:
    knowledge = root / slug / "knowledge"
    knowledge.mkdir(parents=True, exist_ok=True)
    (knowledge / filename).write_text(text, encoding="utf-8")


@pytest.mark.anyio
async def test_search_returns_txt_hit_from_tenant_slug(tmp_path: Path) -> None:
    write_txt(tmp_path, "tenant-a", "hours.txt", "night hours closed exclusive")
    hits = await LabKnowledgeSearch(packages_dir=tmp_path).search(
        tenant_a(), KnowledgeQuery(text="hours")
    )
    assert len(hits) == 1
    hit = hits[0]
    assert hit.tenant_id == TENANT_A
    assert hit.source_id == "hours.txt"
    assert "night hours closed exclusive" == hit.text
    assert hit.document_version == 1
    assert hit.page == 1
    assert hit.document_id == uuid5(NAMESPACE_URL, f"{TENANT_A}/hours.txt")
    assert hit.score > 0


@pytest.mark.anyio
async def test_missing_knowledge_directory_returns_empty(tmp_path: Path) -> None:
    hits = await LabKnowledgeSearch(packages_dir=tmp_path).search(
        tenant_a(), KnowledgeQuery(text="hours")
    )
    assert hits == ()


@pytest.mark.anyio
async def test_ignores_non_txt_and_uuid_directory(tmp_path: Path) -> None:
    write_txt(tmp_path, "tenant-a", "hours.txt", "night hours closed exclusive")
    (tmp_path / "tenant-a" / "knowledge" / "manifest.yaml").write_text(
        "ignored: true\n", encoding="utf-8"
    )
    write_txt(tmp_path, str(TENANT_A), "hours.txt", "uuid-dir must not be read")
    hits = await LabKnowledgeSearch(packages_dir=tmp_path).search(
        tenant_a(), KnowledgeQuery(text="hours")
    )
    assert [hit.source_id for hit in hits] == ["hours.txt"]
    assert all("uuid-dir" not in hit.text for hit in hits)


@pytest.mark.anyio
async def test_unrelated_query_returns_no_hits(tmp_path: Path) -> None:
    write_txt(tmp_path, "tenant-a", "hours.txt", "night hours closed exclusive")
    hits = await LabKnowledgeSearch(packages_dir=tmp_path).search(
        tenant_a(), KnowledgeQuery(text="cardiologia-inexistente")
    )
    assert hits == ()


@pytest.mark.anyio
async def test_limit_caps_ranked_hits(tmp_path: Path) -> None:
    write_txt(tmp_path, "tenant-a", "a.txt", "alpha token overlap hours")
    write_txt(tmp_path, "tenant-a", "b.txt", "beta hours token")
    write_txt(tmp_path, "tenant-a", "c.txt", "gamma hours")
    hits = await LabKnowledgeSearch(packages_dir=tmp_path).search(
        tenant_a(), KnowledgeQuery(text="hours token", limit=2)
    )
    assert len(hits) == 2
    assert hits[0].score >= hits[1].score
