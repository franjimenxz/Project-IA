from pathlib import Path
from uuid import UUID

import pytest

from ia_mcp.knowledge.lab_search import LabKnowledgeSearch
from ia_mcp.knowledge.models import KnowledgeQuery
from ia_mcp.tenancy.models import TenantContext

TENANT_A = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
TENANT_B = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
CORR = UUID("33333333-3333-3333-3333-333333333333")
CANARY_A = "canary-tenant-a exclusive hours"
CANARY_B = "canary-tenant-b night hours closed exclusive"


def tenant(*, tenant_id: UUID, slug: str) -> TenantContext:
    return TenantContext(
        tenant_id=tenant_id,
        tenant_slug=slug,
        config_version=1,
        correlation_id=CORR,
    )


def write_txt(root: Path, slug: str, filename: str, text: str) -> None:
    knowledge = root / slug / "knowledge"
    knowledge.mkdir(parents=True, exist_ok=True)
    (knowledge / filename).write_text(text, encoding="utf-8")


@pytest.mark.anyio
async def test_search_does_not_return_other_tenant_files(tmp_path: Path) -> None:
    write_txt(tmp_path, "tenant-a", "hours-a.txt", CANARY_A)
    write_txt(tmp_path, "tenant-b", "hours-b.txt", CANARY_B)
    search = LabKnowledgeSearch(packages_dir=tmp_path)

    hits_b = await search.search(
        tenant(tenant_id=TENANT_B, slug="tenant-b"),
        KnowledgeQuery(text="hours"),
    )
    blob = " ".join(hit.text for hit in hits_b)
    assert CANARY_B in blob
    assert CANARY_A not in blob
    assert all(hit.tenant_id == TENANT_B for hit in hits_b)
    assert all(hit.source_id != "hours-a.txt" for hit in hits_b)

    hits_a = await search.search(
        tenant(tenant_id=TENANT_A, slug="tenant-a"),
        KnowledgeQuery(text="hours"),
    )
    blob_a = " ".join(hit.text for hit in hits_a)
    assert CANARY_A in blob_a
    assert CANARY_B not in blob_a
    assert all(hit.tenant_id == TENANT_A for hit in hits_a)
