# P04-T13 — Suite integrada del MVP

**Estado:** ready · **Wave:** W5 · **Depends on:** P04-T05, P04-T09–T12

Creá journeys completos y fault injection; no cambiar contratos para hacer pasar tests. Si se detecta incompatibilidad, bloquear con evidencia.

Journeys: FAQ A/B; create→reschedule→reminder→confirm; cancel replay; handoff explícito; handoff por upstream persistente; restart workflow/job; prompt spoofing.

Ejecutá todos los comandos de `../test-plan.md`, Ruff y tipos. Entregá un evidence report por slice y commit `test: verify complete multi-tenant MVP journeys`.

## Lectura obligatoria

Todos los briefs P04 aceptados, `../TDD.md`, `../acceptance-criteria.md`, `../test-plan.md`, Definition of Done y delegation protocol.

## Archivos exactos

Crear/modificar sólo `tests/e2e/test_mvp_journeys.py`, `tests/resilience/test_mvp_failures.py`, `tests/fixtures/mvp.py` y wiring/config de test estrictamente necesario. Contratos, migrations y lógica de dominio están reservados a sus owners.

## Interfaces, rojo/verde y evidencia

Consume APIs públicas de todas las slices; no produce contrato nuevo. Agregar journeys primero y ejecutar cada node para observar el boundary faltante. Tras fixes de wiring aprobados, ejecutar los seis comandos del test plan, `ruff check .` y `mypy src`. Entregar reporte por slice, listas AC-P04-001–027, AC-P04-030–038, AC-P04-040–046 y AC-P04-050–058, runs sintéticos y cero desviaciones o bloqueos explícitos.
