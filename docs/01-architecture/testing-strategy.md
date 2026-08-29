# Estrategia de testing y evals

**Estado:** ready  
**Requisitos:** RNF-001–RNF-015, RF-040

## Pirámide y objetivos

| Capa | Objetivo | Dependencias |
|---|---|---|
| Unit | Reglas, validación y transiciones determinísticas | Ninguna externa |
| Contract | Compatibilidad de puertos, MCP, schemas y adapters | Fake/adapter |
| Integration | SQL, vector, Redis, object store, jobs | Contenedores efímeros |
| E2E | Slice completa | Stack local + proveedores simulados/sandbox |
| Security | Autorización, fugas, injection y secretos | Stack + fixtures adversariales |
| Resilience | Timeouts, replay, caídas y recuperación | Fault injection |
| Evals | Trayectoria probabilística del agente | Dataset versionado |
| Performance | Budgets y escalabilidad | Entorno controlado |

## Ciclo de pruebas primero

Cada comportamiento inicia con una prueba que falla por la ausencia exacta del requisito. El agente registra el comando y motivo del fallo. Luego implementa lo mínimo, confirma verde, refactoriza y ejecuta la suite afectada. Una prueba que falla por environment roto no satisface el paso rojo.

## Organización prevista

```text
tests/
├── unit/
├── contract/
├── integration/
├── e2e/
├── security/
├── resilience/
├── evals/
├── performance/
└── fixtures/
```

Markers Pytest: `unit`, `contract`, `integration`, `e2e`, `security`, `resilience`, `eval`, `performance`, `sandbox`.

## Fixtures base

- `tenant_a`, `tenant_b` con UUIDs distinguibles;
- configuraciones v1/v2 con skills distintas;
- corpus A/B con frases canario únicas;
- conversations y workflows paralelos;
- fake LLM determinístico;
- fake MCP contract-compliant;
- reloj controlado;
- secret store que detecta acceso cruzado;
- channel envelope firmado simulado;
- payloads adversariales.

## Suite multi-tenant mínima

1. A nunca recupera Knowledge B.
2. A nunca obtiene credenciales B.
3. A nunca descubre tools exclusivas B.
4. Conversation A nunca recupera estado B.
5. Un UUID válido de B usado bajo A no revela existencia.
6. Un job de A no ejecuta integration de B.
7. Audit query de tenant admin A no devuelve eventos B.
8. Un prompt que menciona B no modifica TenantContext.
9. Caché/lock keys incluyen tenant.
10. Desactivar A no afecta B.

## Contract tests

La misma suite se ejecuta contra fake y adapters reales:

- request válido/invalid;
- campos obligatorios;
- timezone y fechas;
- paginación;
- respuesta vacía;
- conflicto de slot;
- not found sin fuga;
- rate limit, timeout y 5xx;
- respuesta malformada;
- idempotency/replay;
- sanitización de error.

## Workflow tests

Se prueban tablas de transición, comandos fuera de orden, dos avances concurrentes, reinicio entre pasos, duplicados, retries, estado incierto, compensación y manual review. Los side effects se verifican mediante outbox, no por sleeps.

## RAG y evals

### Dataset

Cada caso incluye:

- tenant;
- config version;
- conversación;
- documentos permitidos;
- intent/skill esperada;
- retrieval esperado/prohibido;
- tools esperadas/prohibidas;
- estado final;
- propiedades de respuesta;
- necesidad de handoff.

### Métricas

- exactitud de tenant y skill;
- recall/precision de retrieval por corpus;
- tool selection y argumentos válidos;
- policy adherence;
- unsupported-claim rate;
- handoff precision/recall;
- workflow completion;
- trajectory correctness;
- latencia y uso normalizado.

No se evalúa sólo similitud textual de respuesta. Las afirmaciones deben estar respaldadas por source IDs o por resultado de tool/workflow.

### Determinismo

PRs usan fake LLM y un subconjunto de evals estable. La suite probabilística usa modelo/version fijada, temperatura controlada cuando el proveedor lo permite, múltiples repeticiones en casos sensibles y umbrales registrados.

## Performance budgets

Fase 2 fija presupuestos iniciales por componente: gateway/tenant, config/state, retrieval, model, tool y persistencia. `EXT-007` reemplaza presupuestos de diseño por SLOs de negocio antes de producción.

Pruebas incluyen concurrencia entre tenants, cola de jobs, corpus creciente, upstream lento y escala horizontal sin afinidad de sesión.

## CI

| Evento | Suites | Estado |
|---|---|---|
| Cada commit | format check, Ruff, types, unit | cubierto por el gate de pull request |
| Pull request | Ruff, tipos, docs/links, unit, contract, integration, security, E2E y aislamiento completo | implementado (`quality.yml`) |
| Merge main | E2E local, aislamiento completo, resilience seleccionada | **pendiente**: no hay workflow disparado por `push` a `main` |
| Programada | evals completas, performance, resilience marcada | implementado (`quality-evidence.yml`, semanal) |
| Release | todas + sandbox real cuando aplique | pendiente hasta `EXT-002` |

El gate de pull request se adelantó respecto del diseño: corre las suites que
la tabla original reservaba para el merge, porque hasta que existieron
`tests/fixtures/database.py` y el job `database-quality` esas suites no corrían
en ningún evento. La fila de merge sigue listada porque un merge puede romper
lo que cada PR verificó por separado; queda como hueco conocido, no como
requisito satisfecho.

## Flakiness

Una prueba flaky se registra como defecto. No se soluciona con retries indiscriminados. Se elimina dependencia de reloj/red/orden o se aísla con owner y fecha de corrección. Tests de retry de negocio usan reloj falso y fault injection determinista.

## Evidencia

Cada reporte incluye commit, entorno, comandos, versiones, conteos, duración, failures, criterios cubiertos y artefactos. Para evals incluye dataset hash, proveedor/modelo, configuración y distribución de resultados.

## Gates

- Ningún merge con unit/contract/integration aplicable en rojo.
- Ninguna slice sin suite negativa tenant.
- Ningún adapter real sin contract suite compartida y sandbox.
- Ninguna release sin evals y seguridad dentro de umbrales aprobados.

