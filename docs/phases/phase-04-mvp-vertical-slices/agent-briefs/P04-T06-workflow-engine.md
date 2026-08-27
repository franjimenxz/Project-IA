# P04-T06 — Workflow Engine durable

**Estado:** ready · **Wave:** W3 · **Depends on:** P02-T03

Implementá state, transitions, command dedupe, CAS y transactional outbox en `workflows/core/*`; no agregar reglas appointments.

Produce `WorkflowEngine.start/advance`, `WorkflowDefinition.transition` y repository público. Probar duplicate command, concurrent advance, invalid transition, crash/reload y tenant crossing.

Verificación `pytest tests/unit/workflows tests/integration/mvp/test_workflow_engine.py tests/resilience/test_workflow_recovery.py -v`. Commit `feat: add durable idempotent workflow engine`.

