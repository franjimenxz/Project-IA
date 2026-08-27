# P04-T10 — Reprogramar y confirmar

**Estado:** ready · **Wave:** W4 · **Depends on:** P04-T08

Implementá dos workflow definitions usando tools canónicas. No simular reschedule con cancel+create.

Probar slot lost sin tocar original, reschedule exitoso, estado incierto, confirm pending/already-confirmed, respuesta ambigua y cross-tenant. Criterios AC-P04-033–038.

Verificación Slice 4.3 E2E/resilience. Commit `feat: reschedule and confirm appointments safely`.

## Lectura obligatoria

Contracts TDD, ADR-003, `../TDD.md` §3, criterios AC-P04-033–038, test plan y Task 10.

## Archivos exactos

Crear `workflows/appointments/reschedule.py`, `confirm.py`, unit tests y `tests/e2e/test_appointment_lifecycle.py`. No implementar fallback cancel+create ni cambiar contracts.

## Interfaces y TDD

Produce `RescheduleAppointmentDefinition` y `ConfirmAppointmentDefinition`; consume ToolExecutor. Rojo: slot lost/success/uncertain/already-confirmed. Verde: `pytest tests/unit/workflows/appointments tests/e2e/test_appointment_lifecycle.py tests/resilience/test_appointment_lifecycle.py -v`. Adjuntar prueba de turno original intacto en slot-lost.
