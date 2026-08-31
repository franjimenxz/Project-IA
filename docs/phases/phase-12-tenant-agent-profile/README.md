# Fase 12 — Perfil de agente por tenant

**Estado:** ready  
**Gate de entrada:** G6 satisfecho; P10-T01 aceptada; Fase 11 aceptada en tablero  
**Salida de fase:** AC-P12-001–AC-P12-008 aceptados; sin gate global nuevo

## Problema

Una institución configura `agent.tone` en el package y en `TenantConfig`, pero ese valor no llega al modelo. `ContextCompiler` lo copia a `CompiledContext.policies` (`src/ia_mcp/agent_runtime/context_compiler.py`) y el harness construye `LLMRequest` sólo con `compiled.core_instructions` (texto fijo de Core, idéntico para todos los tenants). No existe un campo de instrucciones de tenant. El corpus de knowledge es la vía de **información** (hechos recuperables), no de personalidad. `FakeLLM` ignora el request.

## Objetivo

Que el perfil de agente declarado por el tenant —tono e instrucciones opcionales— sea configuración versionada, aislada y presente en cada `LLMRequest` del turno, sin reemplazar las instrucciones de Core ni inventar un system prompt libre, vendor de LLM, consola ni campos institucionales.

## Entregables

- ADR-008 y esta fase;
- extensión aditiva de `AgentConfig` e `LLMRequest`;
- compiler y harness que copian el perfil al request en cada `generate`;
- schema de package y fixture sin secretos;
- suite de aislamiento: el perfil de A no aparece en el request de B.

## Fuera de alcance

- Vendor o adapter real de LLM (`FakeLLM` sigue válido).
- Knowledge retrieval real / embeddings / parser de PDF (`EXT-008`).
- Mutaciones conversacionales (ADR-006 §4).
- WhatsApp real (`EXT-004`), API médica (`EXT-001`–`EXT-003`), consola `/demo`.
- Saludo, voz, avatar, nombre de bot, modelo por tenant.
- Condiciones por slug de institución en Core.

## Regla de arquitectura

Si una institución requiere un `if tenant.slug` para que su tono o instrucciones lleguen al modelo, la tarea se bloquea. La variación vive en `AgentConfig` versionada.

## Tareas

| ID | Resultado |
|---|---|
| [P12-T01](agent-briefs/P12-T01-architecture-docs.md) | ADR-008 y documentación de fase |
| [P12-T02](agent-briefs/P12-T02-profile-contract.md) | Contrato y cableado del perfil |

## Dependencias abiertas

| Tema | Naturaleza | Efecto |
|---|---|---|
| Adapter LLM de producción | Decisión de vendor, no de esta fase | El perfil llega al request; quién lo interpreta fuera de `FakeLLM` queda abierto |
| Loop de tools (Fase 11) | PRs de implementación no mergeados a `main` | Cada `generate` del turno, exista uno o varios, lleva el mismo perfil |

## Lectura obligatoria

- [ADR-002](../../01-architecture/adr/ADR-002-tenant-context-and-isolation.md)
- [ADR-006](../../01-architecture/adr/ADR-006-conversational-tool-loop.md)
- [ADR-008](../../01-architecture/adr/ADR-008-tenant-agent-profile.md)
- [TDD de fase](TDD.md)
- [Criterios](acceptance-criteria.md)
