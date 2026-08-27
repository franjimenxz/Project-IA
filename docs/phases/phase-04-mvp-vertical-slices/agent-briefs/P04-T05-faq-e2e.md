# P04-T05 — FAQ end-to-end

**Estado:** ready · **Wave:** W3 · **Depends on:** P04-T04

Cableá simulated route → conversation → harness → knowledge → outbound outbox/fake channel. No cambiar contratos o ranking.

El E2E publica corpora con canarios A/B, envía preguntas y comprueba respuestas/source IDs diferentes, correlation común, dedupe y config snapshot.

Verificación: todos los comandos Slice 4.1 del test plan. Commit `feat: complete multi-tenant FAQ slice` y evidence report de AC-P04-001–019.

