# Fase 11 — Loop de tool calls en el turno

**Estado:** ready  
**Gate de entrada:** G6 satisfecho; P10-T01 aceptada; ADR-006 aceptado  
**Salida de fase:** AC-P11-001–AC-P11-012 aceptados; sin gate global nuevo

## Problema

El turno conversacional sólo puede responder FAQ. `AgentHarness.handle_message` resuelve la skill literal `"faq"` (`src/ia_mcp/agent_runtime/harness.py:78`), llama al modelo una vez (`:139`) y aplica política (`:165`). `AnswerKind` no tiene forma de expresar una tool call (`src/ia_mcp/agent_runtime/models.py:5`), aunque a cada request se le anuncian tools vía `LLMRequest.tool_names` (`models.py:17`, poblado en `harness.py:136`).

El `ToolExecutor` se construye y se publica en `app.state.tool_executor` (`src/ia_mcp/api/composition.py:228`) y nadie lo lee. `AgentHarness.__init__` ni siquiera lo acepta (`harness.py:31-50`). Los appointments corren por el workflow engine, instanciado sólo desde tests y desde `src/ia_mcp/performance/scenarios.py:160`, sin entrada HTTP y con `run_id` propio (`src/ia_mcp/scheduling/ingress.py:51`).

Toda la maquinaria de las Fases 3, 9 y 10 está construida, testeada y desconectada del turno.

## Objetivo

Que una decisión del modelo pueda ejecutar una tool ya autorizada por ADR-005 y que su resultado vuelva al modelo en la iteración siguiente, con presupuesto acotado, errores tipados, aislamiento por tenant y trazas reales, sin romper ADR-003 ni reintroducir catálogo cerrado en Core.

## Entregables

- ADR-006 y esta fase;
- extensión aditiva del contrato de decisión (`AnswerKind` intacto);
- loop acotado en el harness, consumiendo el executor por turno;
- realimentación del `ToolResult` como evidencia no confiable;
- suite negativa multi-tenant sobre el loop;
- spans `agent.run` y `llm.generate` emitidos y `tool.execute` alcanzable desde un turno.

## Fuera de alcance

- Invocar el workflow engine desde el turno (ADR-006 §4); las mutaciones siguen terminando en `handoff`.
- Cambiar el contrato de `TenantConfig` para declarar superficie de turno o límites por tenant.
- WhatsApp real (`EXT-004`), API médica real (`EXT-001`–`EXT-003`), consola `/demo`, `create_onboarding_router`.
- Reescribir workflows, scheduling o evals de fases anteriores.

## Regla de arquitectura

Si una institución requiere una condición por slug en harness, executor o compiler para que su tool sea invocable en el turno, la tarea se bloquea. La variación vive en configuración, allowlists y el MCP institucional.

## Tareas

| ID | Resultado |
|---|---|
| [P11-T01](agent-briefs/P11-T01-architecture-docs.md) | ADR-006 y documentación de fase |
| [P11-T02](agent-briefs/P11-T02-decision-contract.md) | Contrato de decisión y realimentación |
| [P11-T03](agent-briefs/P11-T03-harness-loop.md) | Loop acotado en el harness |
| [P11-T04](agent-briefs/P11-T04-isolation-observability.md) | Aislamiento, auditoría y trazas |

## Dependencias abiertas

| Tema | Naturaleza | Efecto |
|---|---|---|
| Presupuesto `agent.run` de 800 ms (`src/ia_mcp/performance/models.py:17`) | `EXT-007` más owner de P06-T05 | El objetivo final de latencia del turno con loop no se fija en esta fase |
| Campo de configuración para superficie de turno y límites por tenant | Contrato de config; coordinación de owners | Sin él, el loop queda inerte para catálogos institucionales |
| Sink durable de ejecuciones de tool sin workflow | `src/ia_mcp/observability` más migración; owner P07 | Sin él, las tools del loop no aparecen en la vista de investigación |

## Lectura obligatoria

- [ADR-006](../../01-architecture/adr/ADR-006-conversational-tool-loop.md)
- [ADR-005](../../01-architecture/adr/ADR-005-mcp-discovery-and-generic-invoke.md)
- [ADR-003](../../01-architecture/adr/ADR-003-canonical-contracts-and-workflows.md)
- [TDD de fase](TDD.md)
- [Criterios](acceptance-criteria.md)
