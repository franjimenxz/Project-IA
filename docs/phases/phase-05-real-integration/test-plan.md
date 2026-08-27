# Test Plan — Fase 5

**Estado:** blocked hasta EXT-001–003

| Capa | Casos | Ejecución |
|---|---|---|
| Unit mapping | pure request/response/error transforms | fixtures sanitizadas de docs |
| Contract | suite de Fase 3 | adapter con transport grabado |
| Security | secrets, host allowlist, TLS, redirects, PII | transport fault fixtures |
| Resilience | timeout, 429, 5xx, malformed, unknown outcome | fake transport determinista |
| Sandbox | search/get/create/cancel/reschedule/confirm soportadas | credenciales no productivas |
| E2E | workflows del MVP con MCP real | tenant sandbox dedicado |

No se graban credenciales ni datos reales en cassettes. Payload fixtures se sanitizan y conservan hash/fuente documental.

Gate: contract suite, aislamiento, sandbox, reconcile/rollback y evidencia firmada por owner de integración.

