# Fase 15 — Plugin MCP de laboratorio y WhatsApp simulado

**Estado:** ready  
**Gate de entrada:** Fase 13 y Fase 14 accepted; ADR-011 ready  
**Salida de fase:** AC-P15-001–AC-P15-008 aceptados; sin gate global nuevo

## Problema

El operador quiere un bot por institución al que se le enchufa el MCP que esa sede ya opera. Hoy el form obliga a tildar skills/tools canónicos, el turno solo invoca `appointments.search` / `get`, y esos nombres van al fake aunque exista un SSE en LAN. El chat HTML ya es el canal `simulated`; falta presentarlo como simulación de WhatsApp y que use el catálogo descubierto.

## Objetivo

En development/test: pegar la URL SSE del MCP, descubrir `tools/list`, persistir el endpoint fuera del package, anunciar esas tools al modelo y despacharlas por SSE. El chat de la institución simula WhatsApp (no Cloud). Una rama y un agente por tarea.

## Tareas

| ID | Resultado | Paralelismo |
|---|---|---|
| [P15-T01](agent-briefs/P15-T01-architecture-docs.md) | ADR-011, TDD, AC, briefs | coordinador (esta entrega) |
| [P15-T02](agent-briefs/P15-T02-lab-form-endpoint.md) | Form, `lab_mcp.py`, discovery al guardar, chat como WSP simulado | `accepted` |
| [P15-T03](agent-briefs/P15-T03-runtime-adapt.md) | FAQ, harness, executor, compiler, composition, cliente `tools/list` | `ready` |

## Fuera de alcance

- WhatsApp Cloud, webhooks, plantillas, números (`EXT-004`).
- Inventar auth del MCP institucional (`EXT-003` / P05).
- API médica real (P05).
- Embeddings, PDF, OCR.
- Condiciones por slug en Core.
- Secretos en HTML, logs, traces o git.
- Editar `docs/00-governance/delegation-board.md` (solo coordinador).
