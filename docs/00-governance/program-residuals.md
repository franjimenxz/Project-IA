# Residuales del programa

**Estado:** ready  
**Propósito:** listar lo que no está cerrado y qué se delega ahora. Sin placeholders.

## En curso o listo para delegar

| Ítem | Estado | Acción |
|---|---|---|
| P13-T01 páginas HTML de laboratorio | `in_progress` | Ya hay un agente. No relanzar |
| P14-T01 adaptador Gemini | `ready` | Un agente, una rama |
| P14-T02 knowledge de laboratorio | `ready` | Un agente, una rama |
| P14-T03 FAQ lectura + compiler | `ready` | Un agente, una rama |
| P14-T04 wiring de composition | `blocked` | Esperar T01–T03 `accepted` |

T01–T03 no comparten archivos entre sí ni con P13-T01. T04 comparte `composition.py` con P13-T01: no lanzar T04 mientras P13-T01 esté `in_progress`.

## Fuera de esta wave (no delegar)

| Ítem | Por qué | Gate |
|---|---|---|
| P05-T01–T04 API médica real | EXT-001, EXT-002, EXT-003 sin satisfacer | G4 |
| WhatsApp Cloud | EXT-004 | no inventar proveedor |
| Plataforma de handoff real | EXT-005 | no inventar API |
| Embeddings, PDF, OCR | EXT-008; el lab usa `knowledge/*.txt` | no es Gemini |
| Mutaciones en el turno (`create` / `cancel` / `reschedule` / `confirm`) | ADR-006 §4; siguen por workflow | no abrir en P14 |
| Secret manager de producto | ADR-007 ya mapea `sm://` → `IA_MCP_SECRET_*` | env del operador |
| SLOs, legal, CI obligatorio en push a `main` | residuales P06/P07 | no esta wave |
| Condiciones por slug de institución en Core | CON / ADR-002 | prohibido |

## Demo usable

Hace falta P13-T01 (pantalla) **y** P14-T01–T04 (bot) **y** que el operador exporte `IA_MCP_SECRET_PLATFORM_LLM_GEMINI` en el entorno. Sin esa variable el proceso sigue en `FakeLLM` (fail-closed). Nadie escribe la clave en git, HTML, logs, traces ni fixtures.
