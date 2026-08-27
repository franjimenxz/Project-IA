# P02-T04 — Errores y correlación

**Estado:** ready  
**Wave:** W1  
**Depends on:** P02-T01

Implementá DomainError, Problem Details, redactor y correlation middleware. No registrar bodies/prompts ni integrar backend propietario.

Produce `redact(str) -> str`, error handler y `current_correlation_id() -> UUID`.

Pruebas: bearer, email, nested detail, correlation supplied/generated, stack oculto. Ejecutá unit/API tests, Ruff y tipos.

Commit: `feat: add safe errors and request correlation`.

