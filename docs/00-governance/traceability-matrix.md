# Matriz de trazabilidad

**Estado:** ready  
**Unidad:** requisito → diseño → aceptación → prueba → fase

## Funcional

| Requisitos | Diseño principal | Criterios | Pruebas | Fase |
|---|---|---|---|---|
| RF-001–RF-003 | Tenant/configuration en System TDD | AC-P02-002–007, AC-P02-011–012, AC-P04-001–003, AC-P12-002, AC-P12-006 | Unit + integración + aislamiento | 2, 4.1, 12 |
| RF-004–RF-008 | Agent Harness y Context Compiler | AC-P04-004–008, AC-P12-003–005, AC-P12-007–008 | Unit + eval + autorización | 4.1, 4.2, 12 |
| RF-009–RF-013, RF-043 | Knowledge/RAG TDD | AC-P04-009–014 | Integración + eval + fuga | 4.1 |
| RF-014–RF-018 | Appointment workflow TDD | AC-P04-020–027 | Unit + contrato + E2E | 4.2 |
| RF-019–RF-023 | Lifecycle/workflow TDD | AC-P04-030–038 | E2E + resiliencia | 4.3 |
| RF-024–RF-027 | MCP/contract TDD | AC-P03-005–010, AC-P05-001–010 | Contract tests + sandbox | 3, 5 |
| RF-028–RF-030 | Handoff TDD | AC-P04-040–046 | E2E + eval | 4.4 |
| RF-031–RF-033 | Scheduling TDD | AC-P04-050–058 | Reloj falso + idempotencia | 4.5 |
| RF-034–RF-036, RF-044 | Observability/Security TDD | AC-P07-001–010 | Reconstrucción + sanitización | 4–7 |
| RF-037–RF-039, RF-045 | Security/Onboarding TDD | AC-P08-001–010 | Seguridad + segundo tenant | 2, 8 |
| RF-040 | Testing strategy | AC-P06-001–009 | Pipeline de evals | 6 |
| RF-041–RF-042 | Channel Gateway TDD | AC-P04-015–019 | Contract + integración | 4.1, posterior |

## No funcional

| Requisito | Diseño | Evidencia exigida | Gate |
|---|---|---|---|
| RNF-001 | Security and Multitenancy | Suite negativa completa | Cada slice y G5 |
| RNF-002 | Threat model + autorización | SAST, auth tests, review | G1/G5 |
| RNF-003 | Observability TDD | Reconstrucción de run | G3/G5 |
| RNF-004 | Failure model | Chaos/resiliencia + SLO | G5 |
| RNF-005 | Stateless API/workers | Concurrencia horizontal | G5 |
| RNF-006 | Telemetría OTel | Traces, metrics, logs | G3/G5 |
| RNF-007 | Performance budgets | Load report | G5 |
| RNF-008 | Este documento | Check de cobertura | Cada gate |
| RNF-009 | Component model | Type/lint/review | Cada tarea |
| RNF-010 | Ports/adapters | Segundo adapter/tenant | G5 |
| RNF-011 | Workflow TDD | Replay/duplicate suite | G3 |
| RNF-012 | Security TDD | Sanitización + inventario | G5 |
| RNF-013 | Workflow persistence | Crash/restart suite | G3 |
| RNF-014 | Bootstrap/CI | Checkout limpio en CI | W2 en adelante |
| RNF-015 | Versioning TDD | Migration + contract suite | G2/G5 |

## Casos de uso

| Caso | Requisitos principales | Slice/fase |
|---|---|---|
| UC-01 | RF-001–008, RF-041 | 4.1 |
| UC-02 | RF-014–015, RF-022 | 4.2 |
| UC-03 | RF-016–017, RF-024–026 | 4.2 |
| UC-04 | RF-017–018, RF-023 | 4.2 |
| UC-05 | RF-019, RF-023 | 4.3 |
| UC-06 | RF-017, RF-020, RF-023 | 4.3 |
| UC-07 | RF-021, RF-023 | 4.3/4.5 |
| UC-08 | RF-009–013, RF-043 | 4.1 |
| UC-09 | RF-028–030 | 4.4 |
| UC-10 | RF-031–033 | 4.5 |

## Regla de cierre

Al implementar, cada celda de prueba se reemplaza o amplía con la ruta exacta del test y la evidencia de CI. Ningún requisito `must` puede quedar sin prueba antes del gate correspondiente.
