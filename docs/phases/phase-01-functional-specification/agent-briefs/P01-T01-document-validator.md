# P01-T01 — Validador documental

**Estado:** ready  
**Wave:** W0  
**Plan:** `../implementation-plan.md`

## Objetivo

Crear un CLI Python que detecte IDs de definición duplicados, links locales rotos y placeholders fuera de `docs/templates`. Las referencias repetidas a un ID son válidas; sólo se consideran definiciones la primera columna de registros normativos y los headings declarados por el catálogo.

También debe fallar si un brief carece de lectura obligatoria, archivos, interfaz/secuencia TDD, verificación o commit; si una fase declara el mismo gate de entrada y salida; o si referencia un gate inexistente.

## Lectura obligatoria

`docs/README.md`, `docs/00-governance/requirements-catalog.md`, plan de esta fase.

## Archivos permitidos

`scripts/check_docs.py`, `tests/docs/test_check_docs.py`.

## Exclusiones

No cambiar documentos para ocultar errores ni implementar CI.

## Interfaz

`check_unique_ids(paths: Sequence[Path]) -> list[str]` y CLI `python scripts/check_docs.py --all docs`.

## Criterios

AC-P01-001–005; reportar archivo/línea y exit 1 ante hallazgos.

## Verificación

`pytest tests/docs/test_check_docs.py -v && ruff check scripts tests/docs`.

## Handoff

Usar `delegation-protocol.md`; incluir ejemplos positivo/negativo y commit `test: validate documentation identifiers`.
