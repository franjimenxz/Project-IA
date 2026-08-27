# P01-T02 — Validador de trazabilidad

**Estado:** ready  
**Wave:** W0  
**Depends on:** P01-T01

## Objetivo

Fallar si un RF/RNF `must` no aparece en la matriz global.

## Archivos permitidos

`scripts/check_traceability.py`, `tests/docs/test_traceability.py`.

## Interface

`missing_must_requirements(catalog: str, matrix: str) -> set[str]`.

## Restricciones

Expandir rangos como `RF-001–RF-003`; no considerar texto narrativo fuera de tablas como cobertura.

## Verificación

`pytest tests/docs/test_traceability.py -v && python scripts/check_traceability.py`.

## Evidencia

Casos con ID individual, rango, prioridad no must y requisito faltante. Commit `test: enforce requirement traceability`.

