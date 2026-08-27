# P03-T01 — Contratos comunes

**Estado:** ready  
**Wave:** W2

## Lectura obligatoria

ADR-003, `../TDD.md` results/errors, AC-P03-004/009, test plan y Task 1.

## Archivos exactos

Crear `src/ia_mcp/contracts/common.py`, `errors.py` y `tests/unit/contracts/test_common.py`. No importar adapters, FastAPI o tenant storage.

Creá `NonEmptyStr`, ToolErrorCode, ToolError y `ToolResult[T]`. Restringí cambios a contracts/common, errors y tests. No importar adapters o FastAPI.

ToolResult exige value sólo con `ok=true` y error sólo con `ok=false`. Verificá serialization sin secrets con `pytest tests/unit/contracts/test_common.py -v && mypy src/ia_mcp/contracts`.

Secuencia TDD: empty NonEmptyStr y combinaciones inválidas primero en rojo; implementar models/validator mínimo; ejecutar comando anterior para verde.

Commit: `feat: define canonical tool results`.
