# P04-T05 — FAQ end-to-end

**Estado:** ready · **Wave:** W3 · **Depends on:** P04-T04

Cableá simulated route → conversation → harness → knowledge → outbound outbox/fake channel. No cambiar contratos o ranking.

El E2E publica corpora con canarios A/B, envía preguntas y comprueba respuestas/source IDs diferentes, correlation común, dedupe y config snapshot.

Verificación: todos los comandos Slice 4.1 del test plan. Commit `feat: complete multi-tenant FAQ slice` y evidence report de AC-P04-001–019.

## Lectura obligatoria

`../TDD.md`, `../test-plan.md`, acceptance Slice 4.1, ADR-002/004 y briefs P04-T01–T04.

## Archivos exactos

Modificar `src/ia_mcp/api/routes/simulated.py`, `src/ia_mcp/channels/outbox.py` y app wiring; crear `tests/e2e/test_faq.py` y fixtures E2E. No cambiar contratos, ranking o políticas para acomodar assertions.

## TDD y handoff

Rojo: A/B POST firmado todavía devuelve sólo acknowledgment. Verde: `pytest -m e2e tests/e2e/test_faq.py -v` más todas las suites 4.1. Adjuntar IDs sintéticos correlacionados, dedupe, fuentes A/B, criterios 001–019 y riesgos residuales.
