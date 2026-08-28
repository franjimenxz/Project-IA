# TDD — Composition root de runtime

**ID:** TDD-P10-001  
**Estado:** ready  
**ADRs:** ADR-002, ADR-003, ADR-005  
**Requisitos:** RF-015, RNF-001, RNF-010

## Problema

El grafo de runtime (tenant → config → harness → tools) existe y está cubierto por tests, pero no tiene composition root en `src/`. El proceso HTTP no puede ejecutar un turno.

## Semántica

`create_app` sigue siendo el factory HTTP. La composición vive en un módulo dedicado y se adjunta a `app.state` con los **mismos nombres** que ya consume `src/ia_mcp/api/routes/simulated.py`:

- `tenant_service`
- `config_service`
- `agent_harness`
- `channel_integration_ids`
- `outbox` (ya lo crea `create_app`)
- `tool_executor` (nuevo en state; `SseMcpClient` + `HostAllowlist` + resolver)

## Cuándo cablear

| `IA_MCP_ENVIRONMENT` / `environment=` | `DATABASE_URL` | Comportamiento |
|---|---|---|
| `test` | cualquier | No auto-wire. Los tests siguen inyectando. Simulated sin harness → ACK. |
| `development` | ausente | No auto-wire. Fail-closed: sin harness no hay turno. |
| `development` | presente | Wire runtime desde constructors existentes. Simulated entra al harness. |
| `production` | — | No montar simulated. No cablear `FakeLLM` ni fakes de appointments como si fueran producción. |

`DATABASE_URL` ya lo usa `ia_mcp.onboarding.cli`. No inventar otra variable de conexión.

## Collaborators

Reutilizar constructors e interfaces que ya existen. No inventar API médica, LLM vendor, credenciales ni campos de config.

- `TenantService` + adapter SQL sobre `channel_integration` (tabla ya existe).
- `ConfigurationService` + `SqlAlchemyConfigRepository`.
- `AgentHarness` + repos SQL de conversation/runs + `SkillRegistry` + `ContextCompiler`.
- `LLMPort`: `FakeLLM` en `ia_mcp.agent_runtime.ports` para development. No leer secretos ni pasarlos al LLM.
- Knowledge: no importar fakes de `tests/`. Si no hay parser/embedder en `src/`, un `KnowledgeSearch` vacío fail-closed (FAQ → insufficient). No inventar vendor de embeddings.
- `ToolExecutor`: capability fake versionada (`ia_mcp.mcp.fakes.appointments`) solo en development; transporte `SseMcpClient` solo con resolver + `allowed_hosts`. Host allowlist desde datos de tenant/resolver, no host hardcodeado en Core.
- MCP endpoint y allowlist salen del tenant (integración / config). Cero `if tenant_slug == ...` en Core.

## Simulated

Si hay `AgentHarness` en `app.state`, el POST no puede devolver sólo ACK: debe ir a `harness.handle_message` y responder `SimulatedTurnResponse` (con `run_id`) o 4xx/5xx seguro.

Tests que inyectan únicamente `tenant_service` en `environment="test"` siguen recibiendo ACK.

## Exclusiones

- No WhatsApp.
- No REST médico inventado.
- No secretos en logs, traces, fixtures ni prompts.
- No cambiar contratos Pydantic de config para agregar `endpoint` sin escalar.
- No tocar la consola `/demo` (otra rama).
- No montar `create_onboarding_router` en esta tarea.
