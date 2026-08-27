# P01-T02 — Validador de trazabilidad

**Estado:** ready  
**Wave:** W0  
**Depends on:** P01-T01

## Objetivo

Fallar si un RF/RNF `must` no aparece en la matriz global.

## Lectura obligatoria

`docs/00-governance/requirements-catalog.md`, `docs/00-governance/traceability-matrix.md`, `../TDD.md`, `../test-plan.md` y Task 2 del plan.

## Archivos permitidos

`scripts/check_traceability.py`, `tests/docs/test_traceability.py`.

## Interface

`missing_must_requirements(catalog: str, matrix: str) -> set[str]`.

## Restricciones

Expandir rangos como `RF-001–RF-003`; no considerar texto narrativo fuera de tablas como cobertura.

Expandir también rangos AC completos o abreviados (`AC-P04-050–AC-P04-058` y `AC-P04-050–058`) y fallar ante cualquier criterio referenciado no definido.

## Verificación

`pytest tests/docs/test_traceability.py -v && python scripts/check_traceability.py`.

## Evidencia

Casos con ID individual, rango, prioridad no must y requisito faltante. Commit `test: enforce requirement traceability`.
