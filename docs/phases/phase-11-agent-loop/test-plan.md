# Test Plan — Fase 11

| Suite | Comando | Criterios |
|---|---|---|
| Contrato de decisión | `pytest tests/unit/agent/test_models.py -v` | AC-P11-002, AC-P11-003 |
| Realimentación saneada | `pytest tests/unit/agent/test_tool_observations.py -v` | AC-P11-005 |
| Loop e iteraciones | `pytest tests/unit/agent/test_harness_loop.py -v` | AC-P11-004, AC-P11-006 |
| Superficie invocable | `pytest tests/unit/agent/test_turn_tool_surface.py -v` | AC-P11-007 |
| Errores tipados | `pytest tests/unit/agent/test_harness_loop_errors.py -v` | AC-P11-008, AC-P11-009 |
| Regresión FAQ | `pytest tests/unit/agent/test_harness.py tests/integration/mvp/test_faq_turn.py -v` | AC-P11-012 |
| Aislamiento del loop | `pytest tests/security/test_tool_loop_isolation.py -v` | AC-P11-010 |
| Contratos de tools | `pytest tests/security/test_tool_contracts.py -v` | AC-P11-007, AC-P11-010 |
| Trazas y auditoría | `pytest tests/security/test_observability.py tests/unit/mcp/test_executor.py -v` | AC-P11-011 |
| Evals sin cambio de expectativa | `pytest tests/evals -v` | AC-P11-002, AC-P11-012 |
| Controles estáticos | `ruff check src tests && mypy src/ia_mcp/agent_runtime src/ia_mcp/evals` | AC-P11-002, AC-P11-012 |
| Documentación | `python scripts/check_docs.py --all docs && python scripts/check_traceability.py && pytest tests/docs -q` | AC-P11-001 |

Las rutas de suites nuevas se confirman contra el layout real de `tests/` al abrir cada tarea; si una ya existe, la prueba se agrega ahí en lugar de crear un archivo paralelo.

## Pruebas negativas obligatorias

| Escenario | Resultado esperado |
|---|---|
| Tenant A propone una tool descubierta sólo en el MCP de tenant B | `forbidden` sin invocar transporte; auditoría con `allowed=False` |
| Dos turnos concurrentes de tenants distintos | Cada uno usa un executor construido desde su propio `TenantContext`; ninguna observación cruza |
| Tenant A amplía su allowlist | La superficie invocable de tenant B no cambia |
| Modelo propone una tool canónica que exige idempotency key | `forbidden`; ninguna mutación alcanza la capability |
| Modelo repite el mismo par `(name, arguments)` | El turno termina `insufficient`, sin segunda ejecución |
| MCP devuelve `tenant_isolation_violation` | Aborto sin realimentar al modelo; run `failed` |
| Proveedor LLM cae en la iteración 2 | `insufficient` con `provider_unavailable`; sin mutación parcial que compensar |

## Fuera de CI

Ningún test depende de un host MCP externo ni de un proveedor real. El fake in-process de P09-T03 sigue siendo la fuente de transporte en CI.
