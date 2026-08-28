# Fase 9 — MCP discovery e invocación genérica

**Estado:** ready  
**Gate de entrada:** G5, P08-T04 aceptada; ADR-005 aceptado  
**Gate de salida:** G6 — MCP institucional descubierto e invocable sin catálogo cerrado en Core

## Objetivo

Permitir que cada tenant use el catálogo real de tools expuesto por su MCP institucional (`tools/list`), autorizado por intersección tenant/skill/servidor, e invocado vía `tools/call` genérico. El Core no define qué tools puede ofrecer un MCP ni ramifica por slug de institución.

ADR-003 sigue vigente para contratos canónicos de appointments, fakes, workflows y dispatch especializado cuando el nombre coincide con `appointments.*`.

## Entregables

- ADR-005 y enmienda documental de ADR-003;
- registry sin filtro `KNOWN_TOOLS` como deny-list;
- cliente MCP con discovery SSE (fake in-process para CI);
- executor con rama genérica post-autorización;
- validators/onboarding/evals alineados con nombres descubiertos;
- evidencia de intersección, host allowlist y regression de appointments.

## Regla de arquitectura

Si una institución requiere lógica `if tenant == …` en registry, executor o compiler para exponer tools, la tarea se bloquea. La variación vive en configuración, allowlists y el MCP institucional.

## Tareas

| ID | Resultado |
|---|---|
| [P09-T01](agent-briefs/P09-T01-architecture-docs.md) | Documentación, ADR-005, fase 9 |
| [P09-T02](agent-briefs/P09-T02-open-registry.md) | Registry y allowlists abiertos |
| [P09-T03](agent-briefs/P09-T03-mcp-client.md) | Discovery + cliente SSE |
| [P09-T04](agent-briefs/P09-T04-generic-executor.md) | Executor genérico |

## Lectura obligatoria

- [ADR-005](../../01-architecture/adr/ADR-005-mcp-discovery-and-generic-invoke.md)
- [ADR-003](../../01-architecture/adr/ADR-003-canonical-contracts-and-workflows.md) (amended)
- [system-tdd.md §13](../../01-architecture/system-tdd.md)
- [TDD de fase](TDD.md)
