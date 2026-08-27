# P06-T02 — Runner y scorers

**Estado:** ready · **Depends on:** P06-T01

Implementá runner contra Harness, scorers críticos, reportes JSON/Markdown y compare CLI. No usar judge model para tenant/tool/source exactos.

Probar critical override, baseline regression, dataset/model metadata y redaction. Commit `feat: evaluate complete agent trajectories`.

## Lectura obligatoria

Testing/observability strategies, `../TDD.md`, criteria AC-P06-002–005/009, P06-T01 dataset y Task 2.

## Archivos exactos e interfaces

Crear `src/ia_mcp/evals/runner.py`, `scorers.py`, `report.py`, `cli.py`, unit tests. Consumir Harness y EvalCase; producir `ObservedTrajectory`, `score_trajectory`, JSON/Markdown report y compare CLI. No usar judge para IDs/tools/sources exactos ni guardar reasoning privado.

## TDD/evidencia

Rojo: forbidden tool critical failure y baseline regression. Verde: `pytest tests/evals/unit -v && python -m ia_mcp.evals run --suite smoke --provider fake`. Adjuntar report hash, exit codes y commit.
