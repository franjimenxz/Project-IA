# P02-T04 — Errores y correlación

**Estado:** ready  
**Wave:** W1  
**Depends on:** P02-T01

## Lectura obligatoria

Observability/security strategies, `../TDD.md`, AC-P02-009/010 y Task 4.

## Archivos exactos

Crear `src/ia_mcp/shared/errors.py`, `api/errors.py`, `observability/context.py`, `redaction.py` y unit/API tests. No integrar backend propietario ni loguear body.

Implementá DomainError, Problem Details, redactor y correlation middleware. No registrar bodies/prompts ni integrar backend propietario.

Produce `redact(str) -> str`, error handler y `current_correlation_id() -> UUID`.

Pruebas: bearer, email, nested detail, correlation supplied/generated, stack oculto. Ejecutá unit/API tests, Ruff y tipos.

Commit: `feat: add safe errors and request correlation`.
