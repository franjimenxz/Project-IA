# P07-T04 — Alertas y runbooks

**Estado:** ready · **Depends on:** P07-T01–T03

Definí dashboards/alertas y runbooks para isolation alert, unknown mutation outcome, upstream outage, queue backlog y rollback config/integration.

Cada alerta tiene owner/threshold/window/runbook; cada runbook diagnóstico, mitigación, verificación y escalamiento. Commit `docs: add actionable observability runbooks`.

## Lectura obligatoria

Observability strategy alerts, `../TDD.md`, AC-P07-009/010, Definition of Done y P07-T01–T03 evidence.

## Archivos exactos e interfaces

Crear `observability/dashboards/`, `observability/alerts/`, `docs/runbooks/{isolation,unknown-outcome,upstream,queue,rollback}.md`, `scripts/verify_runbooks.py` y tests. No configurar destination/producto no elegido; usar formato backend-neutral aceptado por adapter futuro.

## TDD/evidencia

Rojo: validator rechaza alert sin owner/runbook y runbook sin verification. Verde: `python scripts/verify_runbooks.py docs/runbooks && pytest tests/docs/test_runbooks.py -v`. Ejecutar tabletop sintético, adjuntar resultado y commit.
