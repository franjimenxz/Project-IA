# P04-T08 — Crear turno

**Estado:** ready · **Wave:** W3 · **Depends on:** P04-T07

Agregá confirmation, revalidation, create, ToolExecution y estados completed/manual review. No implementar otras operaciones.

Idempotency key deriva de workflow/transition; booking token no se muestra/loguea. Probar slot perdido, replay, dos confirms concurrentes, timeout before/after send y response contract violation.

Criterios AC-P04-025–027. Verificación Slice 4.2 E2E/resilience. Commit `feat: create appointments through durable workflow`.

