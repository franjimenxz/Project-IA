# P03-T04 — Fake appointments y contract suite

**Estado:** ready  
**Wave:** W2  
**Depends on:** P03-T02, P03-T03

## Lectura obligatoria

ADR-002/003, `../TDD.md` contracts/Fake MCP, AC-P03-007–010, test plan y Task 4.

## Archivos exactos

Crear `src/ia_mcp/mcp/capabilities/appointments.py`, `mcp/fakes/appointments.py`, `tests/contract/appointments/test_capability.py` y fixtures. No red, SQL o datos reales.

Implementá Protocol con `TenantContext` explícito en todas las operaciones, fake por tenant y suite parametrizable para search/get/create/cancel/reschedule/confirm. El fake usa clock/ID factories y fault plan; no red, SQL ni datos reales.

Casos: idempotencia, cross-tenant not found, slot conflict, timeout/rate limit/malformed response y transiciones válidas.

Verificación: `pytest -m contract tests/contract/appointments -v && mypy src/ia_mcp/mcp`.

Commit: `test: provide contract-compliant appointment fake`.
