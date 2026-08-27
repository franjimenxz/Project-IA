# P04-T09 — Cancelación

**Estado:** ready · **Wave:** W4 · **Depends on:** P04-T08

Implementá workflow get→confirm→cancel usando contratos; no editar create/reschedule. Already cancelled es éxito idempotente; ID de B bajo A no revela existencia.

Probar política disabled, confirm negada, replay, conflict, timeout incierto y cross-tenant. Criterios AC-P04-030–032, 038.

Verificación lifecycle/security suites. Commit `feat: cancel appointments idempotently`.

## Lectura obligatoria

Contracts TDD, ADR-002/003, `../TDD.md` §3, criterios AC-P04-030–032/038 y Task 9.

## Archivos exactos

Crear `src/ia_mcp/workflows/appointments/cancel.py`, `tests/unit/workflows/appointments/test_cancel.py`, `tests/e2e/test_appointment_cancel.py`. No modificar create/reschedule/confirm o adapter.

## Interfaces y TDD

Consume Workflow Engine y ToolExecutor; produce `CancelAppointmentDefinition`. Rojo: confirm/replay/already-cancelled/cross-tenant nodes; verde: `pytest tests/unit/workflows/appointments/test_cancel.py tests/e2e/test_appointment_cancel.py tests/security/test_tenant_isolation.py -v`. Evidence report y commit indicado.
