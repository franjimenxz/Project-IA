# P02-T01 — Bootstrap FastAPI

**Estado:** ready  
**Wave:** W1  
**Plan:** `../implementation-plan.md`

**Depends on:** P01-T03

## Objetivo y resultado

Crear un checkout reproducible de Python/FastAPI con calidad automatizada, contenedores y un liveness probe que no dependa de base de datos, proveedor LLM ni servicios externos.

## Lectura obligatoria

`docs/README.md`, `docs/01-architecture/system-tdd.md`, `docs/01-architecture/testing-strategy.md`, `docs/01-architecture/adr/ADR-001-modular-monolith.md`, `../TDD.md`, `../acceptance-criteria.md` y Task 1 de `../implementation-plan.md`.

## Alcance

Incluye packaging, app factory, liveness, test unitario, Compose local y workflow de calidad. No incluye modelos de negocio, acceso a DB, migraciones, tenancy, readiness, proveedor LLM ni integraciones externas.

## Archivos exactos

Crear `pyproject.toml`, `src/ia_mcp/__init__.py`, `src/ia_mcp/api/app.py`, `tests/unit/api/test_app.py`, `compose.yaml` y `.github/workflows/quality.yml`. No modificar contratos, dominio ni documentación de otras fases.

## Interfaces

Produce `create_app() -> FastAPI` y `GET /health/live -> 200 {"status":"alive"}`. El endpoint debe responder sin inicializar dependencias externas.

## TDD y verificación

1. Escribir `test_liveness_does_not_require_dependencies` exactamente desde Task 1 del plan.
2. Ejecutar `pytest tests/unit/api/test_app.py::test_liveness_does_not_require_dependencies -v`; el rojo esperado es import/app inexistente.
3. Implementar el packaging, la app factory y la ruta mínimos para volver verde el test.
4. Ejecutar nuevamente el test dirigido; debe terminar con exit 0 y el payload exacto.
5. Ejecutar `ruff check . && mypy src && pytest tests/unit -v`; toda la secuencia debe terminar con exit 0.

## Evidencia y commit

Adjuntar comandos y salidas red/green, versión de Python resuelta, AC-P02-001 y resultado del workflow de calidad. Handoff con commit `chore: bootstrap FastAPI platform`.
