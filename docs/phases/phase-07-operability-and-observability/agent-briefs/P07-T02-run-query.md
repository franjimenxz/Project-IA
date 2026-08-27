# P07-T02 — Run investigation query

**Estado:** ready · **Depends on:** Fase 4 integrada

Implementá `RunInvestigationQuery.get(tenant, run_id)` con summaries y pagination. Permitidos query models/adapter/tests; no modificar tablas owners ni exponer payloads.

Probar run completo, cross-tenant 404, missing refs y redaction. Commit `feat: reconstruct agent run investigations`.

## Lectura obligatoria

Data model, security/observability strategies, `../TDD.md`, AC-P07-001/002/004/005 y Task 2.

## Archivos exactos e interfaces

Crear `src/ia_mcp/observability/run_models.py`, `run_query.py`, `adapters/sqlalchemy_run_query.py`, integration tests. No modificar tablas owners ni exponer message/chunk/payload. Produce `RunInvestigationQuery.get(TenantContext, UUID) -> RunInvestigation`.

## TDD/evidencia

Rojo: run B bajo A no falla/not found; verde `pytest tests/integration/observability/test_run_query.py tests/security/test_observability.py -v && mypy src/ia_mcp/observability`. Adjuntar timeline fixture y 404 uniforme.
