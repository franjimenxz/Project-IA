# P06-T04 — Resiliencia y recovery

**Estado:** ready · **Depends on:** Fase 4 integrada

Inyectá fallos determinísticos en DB, Redis, LLM, KB, MCP, channel y handoff, antes/después de side effects. Verificá no duplicación, recovery o manual review.

No usar sleeps/red real. Commit `test: verify workflow resilience and recovery`.

## Lectura obligatoria

System failure model, workflow/scheduling TDDs, `../TDD.md`, AC-P06-007 y Phase 4 test plan.

## Archivos exactos e interfaces

Crear `tests/fixtures/faults.py`, `tests/resilience/test_dependencies.py`, `test_workflow_recovery.py`, `test_scheduler_recovery.py`. Consumir fault-plan ports existentes; cambios de hooks se limitan a fakes. No red real/sleeps.

## TDD/evidencia

Rojo por boundary before/after side effect; verde: `pytest -m resilience tests/resilience -v`. Reportar estado final, side-effect count, retry/manual review/recovery, AC-P06-007 y commit.
