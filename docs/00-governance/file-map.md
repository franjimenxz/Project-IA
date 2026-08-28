# Mapa de archivos de implementación

**Estado:** ready  
**Objetivo:** fijar ownership y evitar que tareas vecinas creen estructuras incompatibles.

## Raíz

| Ruta | Responsabilidad | Primera tarea owner |
|---|---|---|
| `pyproject.toml` | dependencias, tools y metadata | P02-T01 |
| `compose.yaml` | servicios locales reproducibles | P02-T01 |
| `.github/workflows/quality.yml` | gates CI | P01-T03/P02-T01 |
| `alembic/` | migraciones versionadas | P02-T03 |
| `tests/` | suites por capa | tarea que introduce comportamiento |
| `evals/` | datasets y baselines sintéticos | P06-T01 |
| `tenants/` | packages declarativos sin secretos | P08-T01 |

## Paquetes

| Ruta | Responsabilidad | Owner inicial |
|---|---|---|
| `src/ia_mcp/api/` | adapters HTTP/FastAPI, auth de entrada y composition root | P02-T01 / P10-T01 |
| `src/ia_mcp/channels/` | envelopes, adapters y delivery | P02-T05 |
| `src/ia_mcp/tenancy/` | TenantContext y resolución | P02-T02 |
| `src/ia_mcp/configuration/` | config versionada | P02-T03 |
| `src/ia_mcp/conversation/` | Conversation, Message y SessionState | P04-T01 |
| `src/ia_mcp/agent_runtime/` | Harness, runs, LLM port, context | P04-T02/P04-T04 |
| `src/ia_mcp/skills/` | registry y skills MVP | P04-T02 |
| `src/ia_mcp/contracts/` | modelos canónicos públicos | P03-T01 |
| `src/ia_mcp/knowledge/` | ingestión, documentos y retrieval | P04-T03 |
| `src/ia_mcp/workflows/` | engine y definitions de negocio | P04-T06 |
| `src/ia_mcp/mcp/` | registry, resolver, discovery, client, executor y capabilities | P03-T03/P03-T04/P03-T05, P09-T02–T04 |
| `src/ia_mcp/integrations/` | adapters institucionales | P05-T02 |
| `src/ia_mcp/handoff/` | transferencia y ownership | P04-T11 |
| `src/ia_mcp/scheduling/` | jobs, clock, reminder | P04-T12 |
| `src/ia_mcp/onboarding/` | package/lifecycle/preflight | P08-T01 |
| `src/ia_mcp/evals/` | runner, scorers y reportes | P06-T01 |
| `src/ia_mcp/observability/` | correlation, audit y run queries | P02-T04/P07-T01 |
| `src/ia_mcp/shared/` | errores/primitivas realmente transversales | P02-T04 |

## Reglas de ownership

- El primer owner define la interfaz según el TDD aprobado.
- Consumidores no editan internals del owner; solicitan cambio de contrato.
- Un archivo tiene un agente activo por wave.
- Migraciones previas no se reescriben después de aceptarse; se agrega una nueva.
- `shared` no recibe lógica de dominio ni helpers con un solo consumidor.
- Tests contractuales viven fuera del adapter concreto y se parametrizan.

## Cambios que requieren coordinación

`pyproject.toml`, CI, migraciones, contratos públicos, TenantContext, errores comunes, semantic conventions y schemas de config requieren revisión de owners afectados aunque aparezcan en el scope de una tarea.
