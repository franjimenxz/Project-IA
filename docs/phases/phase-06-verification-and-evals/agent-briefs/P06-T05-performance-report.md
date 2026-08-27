# P06-T05 — Performance y release report

**Estado:** ready · **Depends on:** P06-T02–T04, EXT-007 para SLO final

Implementá escenarios controlados, report schema, baseline comparison y scheduled/release CI. No afirmar capacidad productiva sin volumen aprobado.

Entregar budgets por span, throughput/errors/queue y commit `ci: gate releases on quality evidence`.

## Lectura obligatoria

Testing/observability strategies, `../TDD.md`, AC-P06-008/009, P06-T02–T04 reports y EXT-007.

## Archivos exactos e interfaces

Crear `src/ia_mcp/performance/models.py`, `cli.py`, scenarios, `src/ia_mcp/evals/quality_report.py`, tests y CI scheduled job. No declarar SLO productivo sin EXT-007 ni versionar outputs voluminosos.

## TDD/evidencia

Rojo: report sin latency/errors/queue metrics se rechaza. Verde: `python -m ia_mcp.performance run --scenario mvp-baseline` y quality aggregator/tests. Entregar environment/baseline hash, compare outcome, gate decision y commit.
