# P03-T01 — Contratos comunes

**Estado:** ready  
**Wave:** W2

Creá `NonEmptyStr`, ToolErrorCode, ToolError y `ToolResult[T]`. Restringí cambios a contracts/common, errors y tests. No importar adapters o FastAPI.

ToolResult exige value sólo con `ok=true` y error sólo con `ok=false`. Verificá serialization sin secrets con `pytest tests/unit/contracts/test_common.py -v && mypy src/ia_mcp/contracts`.

Commit: `feat: define canonical tool results`.

