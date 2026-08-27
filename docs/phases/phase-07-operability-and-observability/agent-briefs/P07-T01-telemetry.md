# P07-T01 — Telemetría correlacionada

**Estado:** ready · **Wave:** W6

Estandarizá atributos y propagación HTTP/outbox/worker/MCP sin cambiar lógica de negocio. Probar trace único, retry link, exporter failure y cardinalidad.

No registrar content/payload/secrets. Commit `feat: correlate telemetry across async boundaries`.

## Lectura obligatoria

Observability/security strategies, semantic spans in System TDD, `../TDD.md`, AC-P07-006–008 y Task 1.

## Archivos exactos e interfaces

Crear `src/ia_mcp/observability/semconv.py`, `propagation.py`, tests; modificar middleware/outbox/worker/MCP hooks sólo para carrier. Produce helpers versionados y context inject/extract; no cambia resultado de negocio.

## TDD/evidencia

Rojo: E2E muestra trace/correlation cortado; verde `pytest tests/integration/observability/test_propagation.py tests/resilience/test_telemetry.py tests/security/test_observability.py -v`. Entregar span tree sanitizado, cardinality result y commit.
