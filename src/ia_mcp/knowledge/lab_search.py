from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from ia_mcp.knowledge.models import KnowledgeHit, KnowledgeQuery
from ia_mcp.tenancy.models import TenantContext


def _tokens(text: str) -> frozenset[str]:
    tokens: list[str] = []
    current: list[str] = []
    for char in text.lower():
        if char.isalnum():
            current.append(char)
            continue
        if current:
            tokens.append("".join(current))
            current = []
    if current:
        tokens.append("".join(current))
    return frozenset(tokens)


class LabKnowledgeSearch:
    def __init__(self, *, packages_dir: Path) -> None:
        self._packages_dir = packages_dir

    async def search(
        self, tenant: TenantContext, query: KnowledgeQuery
    ) -> tuple[KnowledgeHit, ...]:
        directory = self._packages_dir / tenant.tenant_slug / "knowledge"
        if not directory.is_dir():
            return ()
        query_tokens = _tokens(query.text)
        if not query_tokens:
            return ()
        hits: list[KnowledgeHit] = []
        for path in sorted(directory.glob("*.txt")):
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8")
            overlap = len(query_tokens & _tokens(text))
            if overlap == 0:
                continue
            filename = path.name
            hits.append(
                KnowledgeHit(
                    tenant_id=tenant.tenant_id,
                    source_id=filename,
                    text=text,
                    score=overlap / len(query_tokens),
                    document_id=uuid5(NAMESPACE_URL, f"{tenant.tenant_id}/{filename}"),
                    document_version=1,
                    page=1,
                )
            )
        hits.sort(key=lambda hit: (-hit.score, hit.source_id))
        return tuple(hits[: query.limit])
