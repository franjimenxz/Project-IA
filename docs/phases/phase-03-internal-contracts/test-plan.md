# Test Plan — Fase 3

| Suite | Cobertura | Comando |
|---|---|---|
| Unit schemas | campos, fechas, timezone, extra, serialization | `pytest tests/unit/contracts -v` |
| Registry | intersección y forbidden | `pytest tests/unit/mcp/test_registry.py -v` |
| Executor | segunda autorización, dispatch y cero llamada denegada | `pytest tests/unit/mcp/test_executor.py -v` |
| Contract | todas las appointment capabilities y errores | `pytest -m contract tests/contract/appointments -v` |
| Security | schema sin tenant/secrets y redaction | `pytest -m security tests/security/test_tool_contracts.py -v` |

La contract suite usa factory fixture `appointment_capability` para ejecutarse contra fake y, en Fase 5, adapter sandbox.

Gate: AC-P03-001–010, JSON schemas snapshot versionados, executor fail-closed y mypy sin `Any` en contracts públicos.
