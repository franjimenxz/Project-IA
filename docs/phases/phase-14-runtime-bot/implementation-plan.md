# Plan de implementación — Fase 14

## Orden

```
P14-T01 Gemini adapter     ──┐
P14-T02 Lab knowledge      ──┼── ready en paralelo (no comparten archivos)
P14-T03 FAQ read tools     ──┘
                │
                ▼
P14-T04 Runtime wiring     (blocked hasta que T01–T03 estén accepted)
```

P13-T01 (páginas HTML) no comparte archivos con T01–T03. Puede seguir en paralelo. T04 toca `composition.py`; no se lanza hasta aceptar T01–T03 ni mientras P13-T01 tenga ese archivo reservado.

## T01 — Gemini adapter

Crear `src/ia_mcp/llm/gemini.py` y tests. `generate` async; lanza `LLMError`. No editar `composition.py` ni `FakeLLM`.

## T02 — Lab knowledge

Crear `src/ia_mcp/knowledge/lab_search.py` y tests. Path por **slug**. No editar `composition.py`. `EmptyKnowledgeSearch` permanece.

## T03 — FAQ + compiler

Editar `faq.py` y `context_compiler.py` + tests. Término tenant = `config.enabled_tools`. `server_tools` acepta `frozenset` de proceso. No editar `composition.py`.

## T04 — Wiring

Editar `composition.py` para instanciar T01–T03. Fail-closed si no hay secreto o no hay packages dir.

## Verificación por tarea

Ver el brief. El coordinador no marca `accepted` sin evidencia de `pytest` + `check_docs` + `check_traceability` cuando el cambio toca docs.
