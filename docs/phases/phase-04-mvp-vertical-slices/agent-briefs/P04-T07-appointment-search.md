# P04-T07 — Appointment fields y búsqueda

**Estado:** ready · **Wave:** W3 · **Depends on:** P04-T06, P03-T05

Implementá estados collecting/searching/selection y AppointmentSkill. No crear/cancelar. Required fields provienen de TenantConfig; tool search se ejecuta mediante registry/executor.

Probar config A/B diferente, invalid data, no slots, timeout, tool disabled, results sanitizados y MCP target A/B. Criterios AC-P04-020–024.

Verificación unit + contract + integration. Commit `feat: collect appointment fields and search slots`.

## Lectura obligatoria

Contracts TDD, P03-T05 brief, `../TDD.md` §§2/6, criterios AC-P04-020–024 y Task 7.

## Archivos exactos

Crear `src/ia_mcp/workflows/appointments/create.py`, `src/ia_mcp/skills/appointments.py`, unit/integration tests. Consumir sin modificar Workflow Engine, contracts, ToolExecutor y fake capability.

## Interfaces y TDD

Produce `CreateAppointmentDefinition` hasta `awaiting_slot_selection` y AppointmentSkill routing. Rojo: tabla tenant A/B required_fields; verde: `pytest tests/unit/workflows/appointments tests/integration/mvp/test_appointment_search.py -v && pytest -m contract tests/contract/appointments -v`. Evidencia de ToolExecutor/MCP tenant target y slots sanitizados.
