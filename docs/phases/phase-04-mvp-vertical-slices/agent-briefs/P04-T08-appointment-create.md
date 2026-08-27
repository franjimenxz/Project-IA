# P04-T08 — Crear turno

**Estado:** ready · **Wave:** W3 · **Depends on:** P04-T07

Agregá confirmation, revalidation, create, ToolExecution y estados completed/manual review. No implementar otras operaciones.

Idempotency key deriva de workflow/transition; booking token no se muestra/loguea. Probar slot perdido, replay, dos confirms concurrentes, timeout before/after send y response contract violation.

Criterios AC-P04-025–027. Verificación Slice 4.2 E2E/resilience. Commit `feat: create appointments through durable workflow`.

## Lectura obligatoria

ADR-003, contracts TDD, `../TDD.md` §§2/6, criterios 4.2, test plan y Task 8.

## Archivos exactos

Modificar `workflows/appointments/create.py` y ToolExecutor audit adapter; crear `tests/e2e/test_appointment_create.py` y resilience cases. No cambiar schemas, registry o fake semantics.

## Interfaces y TDD

Consume `ToolExecutor.execute(TenantContext, run_id, ToolCall)`; produce transitions confirmation→revalidation→create→completed/manual review. Rojo: replay E2E produce dos o cero appointments; verde: `pytest -m e2e tests/e2e/test_appointment_create.py -v && pytest -m resilience tests/resilience/test_appointment_create.py -v`. Adjuntar one-mutation count y ToolExecution sanitizada.
