# P14-T02 — Knowledge de laboratorio

**Estado:** accepted · **Wave:** W13 · **Depends on:** Fase 12 accepted

Crear `LabKnowledgeSearch` que lee `{packages_dir}/{tenant.tenant_slug}/knowledge/*.txt` en proceso. Sin embeddings. Sin tocar `composition.py`.

Commit: `feat: add lab package knowledge search (P14-T02)`

## Lectura obligatoria

1. `docs/README.md`
2. `docs/00-governance/delegation-protocol.md`
3. [ADR-010](../../../01-architecture/adr/ADR-010-gemini-runtime-llm.md)
4. [../TDD.md](../TDD.md)
5. [../acceptance-criteria.md](../acceptance-criteria.md) (AC-P14-005, AC-P14-010)
6. [../test-plan.md](../test-plan.md)
7. Código: `src/ia_mcp/agent_runtime/ports.py` (`KnowledgeSearch`), `src/ia_mcp/knowledge/models.py` (`KnowledgeHit`, `KnowledgeQuery`), `src/ia_mcp/api/composition.py` (`EmptyKnowledgeSearch`, no editar), `tenants/fixtures/tenant-b/knowledge/`

## Archivos permitidos

**Crear:**

- `src/ia_mcp/knowledge/lab_search.py`
- `tests/unit/knowledge/test_lab_search.py`
- `tests/security/test_lab_knowledge_isolation.py`

**No tocar:**

- `src/ia_mcp/api/composition.py` (`EmptyKnowledgeSearch` se queda)
- embeddings, PDF, OCR, secretos, `docs/00-governance/delegation-board.md`

## Interfaces

```python
class LabKnowledgeSearch:
    def __init__(self, *, packages_dir: Path) -> None: ...
    async def search(
        self, tenant: TenantContext, query: KnowledgeQuery
    ) -> tuple[KnowledgeHit, ...]: ...
```

Reglas:

- El directorio es el **slug** (`tenant.tenant_slug`), no el UUID. Ejemplo de fixture: `tenants/fixtures/tenant-b/knowledge/hours-b.txt`.
- Solo `*.txt`. Si el directorio no existe, `()`.
- `source_id` = nombre de archivo (`hours-b.txt`).
- `KnowledgeHit` exige `document_id`, `document_version`, `page`, `score`, `tenant_id`. `document_id` = `uuid5` estable de `tenant.tenant_id` + nombre de archivo. `document_version=1`, `page=1`.
- Ranking: substring / token overlap acotado por `query.limit`. Sin red.
- No lee el paquete de otro slug.

## TDD

1. Rojo: fixture temporal con dos slugs; query que solo matchea A.
2. Implementación mínima.
3. Verde + isolation A/B.

## Verificación

```text
pytest tests/unit/knowledge/test_lab_search.py tests/security/test_lab_knowledge_isolation.py -v
ruff check src/ia_mcp/knowledge/lab_search.py tests/unit/knowledge/test_lab_search.py tests/security/test_lab_knowledge_isolation.py
```

Criterios: AC-P14-005, AC-P14-010.

## Exclusiones

- No cablear composition (T04).
- No borrar `EmptyKnowledgeSearch`.
- No editar el tablero.
