# P04-T03 — Knowledge ingestion y retrieval

**Estado:** ready · **Wave:** W3 · **Depends on:** P02-T03

Implementá documentos/versiones/chunks, ports de parser/embedding/object store, publicación y search tenant-scoped. No implementar FAQ/LLM ni usar PDFs reales.

Produce `KnowledgeIngestor.ingest/publish` y `KnowledgeService.search`. PostgreSQL/pgvector adapter filtra tenant+published antes de ranking y post-valida ownership.

Criterios AC-P04-009–011, 017–019. Fixtures con canarios A/B, draft/failed y parser fault. Verificación integration + isolation. Commit `feat: isolate tenant knowledge ingestion and search`.

