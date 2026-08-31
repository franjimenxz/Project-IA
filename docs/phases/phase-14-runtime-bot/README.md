# Fase 14 — Cerrar el bot de runtime

**Estado:** accepted  
**Gate de entrada:** G6 satisfecho; Fase 12 accepted; vendor Gemini decidido (ADR-010)  
**Salida de fase:** AC-P14-001–AC-P14-010 aceptados; sin gate global nuevo

## Problema

El harness de development no puede cerrar una demo. Cuatro huecos independientes:

1. `FakeLLM` ignora el `LLMRequest` (`del request`).
2. `EmptyKnowledgeSearch` no lee el package.
3. `FAQSkill.allowed_tools` siempre `frozenset()`, así que el loop de Fase 11 no tiene tools.
4. `ContextCompiler` arranca con `tenant_tools={}` y catálogo servidor vacío; la intersección es vacía aunque FAQ anunciara tools.

El perfil (ADR-008) ya llega al request. Nadie lo consume.

## Objetivo

Gemini lee el `LLMRequest` (Core + perfil + evidencia + tools). El knowledge de laboratorio recupera texto del package por slug. FAQ anuncia `appointments.search` / `appointments.get` si están en `enabled_tools`. Composition cablea todo. Una rama y un agente por tarea.

## Tareas

| ID | Resultado | Paralelismo |
|---|---|---|
| [P14-T01](agent-briefs/P14-T01-gemini-adapter.md) | `GeminiLLM` | `accepted` |
| [P14-T02](agent-briefs/P14-T02-lab-knowledge.md) | Búsqueda de knowledge del package | `accepted` |
| [P14-T03](agent-briefs/P14-T03-faq-read-tools.md) | FAQ lectura + compiler usa `enabled_tools` | `accepted` |
| [P14-T04](agent-briefs/P14-T04-runtime-wiring.md) | Composition: Gemini + knowledge + catálogo servidor | `accepted` |

Fase 14 T01–T04 accepted.

## Fuera de alcance

- WhatsApp real, API médica, embeddings/PDF, vendor distinto de Gemini.
- Mutaciones `create` / `cancel` / `reschedule` / `confirm` desde el turno.
- Páginas HTML (P13-T01).
- Editar `FakeLLM` de tests.

El inventario de residuales del programa (EXT, mutaciones, producción) está en [program-residuals.md](../../00-governance/program-residuals.md).

## Lectura

- [ADR-010](../../01-architecture/adr/ADR-010-gemini-runtime-llm.md)
- [TDD](TDD.md)
- [Criterios](acceptance-criteria.md)
- [Plan](implementation-plan.md)
- [Test plan](test-plan.md)
