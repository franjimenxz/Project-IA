# P04-T06 — Workflow Engine durable

**Estado:** ready · **Wave:** W3 · **Depends on:** P02-T03

Implementá state, transitions, command dedupe, CAS y transactional outbox en `workflows/core/*`; no agregar reglas appointments.

Produce `WorkflowEngine.start/advance`, `WorkflowDefinition.transition` y repository público. Probar duplicate command, concurrent advance, invalid transition, crash/reload y tenant crossing.

Verificación `pytest tests/unit/workflows tests/integration/mvp/test_workflow_engine.py tests/resilience/test_workflow_recovery.py -v`. Commit `feat: add durable idempotent workflow engine`.

## Lectura obligatoria

System TDD §12/17, data model, ADR-003/004, `../TDD.md`, criterios 4.2 y Task 6.

## Archivos exactos

Crear `src/ia_mcp/workflows/models.py`, `definition.py`, `engine.py`, `ports.py`, `adapters/sqlalchemy.py`, migración `0004_workflows.py` y tests indicados. No agregar states de appointments o llamadas MCP.

## Interfaces y evidencia

Consume `TenantContext`, transaction/outbox ports; produce `WorkflowEngine.start/advance` y `WorkflowDefinition.transition`. Rojo: duplicate command node; verde: comando anterior + mypy. Adjuntar transition table, CAS conflict, crash/reload y tenant-negative evidence.
