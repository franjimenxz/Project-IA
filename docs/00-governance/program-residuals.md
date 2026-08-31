# Residuales del programa

**Estado:** ready  
**Propósito:** listar lo que no está cerrado y qué se delega ahora. Sin placeholders.

## En curso o listo para delegar

| Ítem | Estado | Acción |
|---|---|---|
| P13-T01 páginas HTML de laboratorio | `accepted` | PR #91 (`a92d9af`) |
| P14-T01 adaptador Gemini | `accepted` | PR #93 (`c9c23b5`) |
| P14-T02 knowledge de laboratorio | `accepted` | PR #89 (`83a3f22`) |
| P14-T03 FAQ lectura + compiler | `accepted` | PR #92 (`47081d9`) |
| P14-T04 wiring de composition | `ready` | Un agente. Solo `composition.py` y `test_composition.py` |

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

Hace falta P14-T04 **y** que el operador exporte `IA_MCP_SECRET_PLATFORM_LLM_GEMINI` en el entorno. Sin esa variable el proceso sigue en `FakeLLM` (fail-closed). Nadie escribe la clave en git, HTML, logs, traces ni fixtures.
