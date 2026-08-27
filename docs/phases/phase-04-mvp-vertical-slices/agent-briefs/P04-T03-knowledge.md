# P04-T03 — Knowledge ingestion y retrieval

**Estado:** ready · **Wave:** W3 · **Depends on:** P02-T03

Implementá documentos/versiones/chunks, ports de parser/embedding/object store, publicación y search tenant-scoped. No implementar FAQ/LLM ni usar PDFs reales.

Produce `KnowledgeIngestor.ingest/publish` y `KnowledgeService.search`. PostgreSQL/pgvector adapter filtra tenant+published antes de ranking y post-valida ownership.

Criterios AC-P04-009–011, 017–019. Fixtures con canarios A/B, draft/failed y parser fault. Verificación integration + isolation. Commit `feat: isolate tenant knowledge ingestion and search`.

## Lectura obligatoria

System TDD §11, data model, security TDD, ADR-002/004, `../TDD.md`, criterios y Task 3.

## Archivos exactos

Crear `src/ia_mcp/knowledge/models.py`, `ports.py`, `service.py`, `adapters/sqlalchemy.py`, `adapters/object_store.py`, migración `0003_knowledge.py`, unit/integration/security tests. No implementar FAQ, prompts o proveedor productivo de embeddings.

## Interfaces y TDD

Consume `TenantContext`, Parser/Chunker/Embedding/ObjectStore ports; produce `KnowledgeIngestor.ingest/publish` y `KnowledgeService.search`. Rojo: search A devuelve canario B o service ausente; verde: `pytest -m integration tests/integration/mvp/test_knowledge.py -v && pytest -m security tests/security/test_tenant_isolation.py -v`. Adjuntar query/constraint evidence sin contenido sensible.
