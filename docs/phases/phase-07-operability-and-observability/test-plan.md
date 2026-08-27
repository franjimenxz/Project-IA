# Test Plan — Fase 7

| Suite | Comando |
|---|---|
| Read model | `pytest tests/integration/observability/test_run_query.py -v` |
| Admin API/view/RBAC | `pytest tests/integration/api/test_run_investigation.py -v` |
| Propagation/exporter | `pytest tests/resilience/test_telemetry.py -v` |
| Redaction/cardinality | `pytest tests/security/test_observability.py -v` |
| Runbook exercise | `python scripts/verify_runbooks.py docs/runbooks` |

Fixtures: successful FAQ, appointment with retry, unknown outcome, handoff, reminder job, tenant A/B and principals operator/auditor/platform admin.

Gate: AC-P07-001–010 y ejercicio tabletop con evidence report.

