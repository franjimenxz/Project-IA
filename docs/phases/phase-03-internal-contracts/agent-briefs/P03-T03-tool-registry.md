# P03-T03 — Tool registry

**Estado:** ready  
**Wave:** W2  
**Depends on:** P02-T02

## Lectura obligatoria

System TDD Skills/MCP, ADR-002/003, `../TDD.md`, AC-P03-005/006 y Task 3.

## Archivos exactos

Crear `src/ia_mcp/mcp/registry.py`, `tests/unit/mcp/test_registry.py` y security cases. No ejecutar MCP, resolver secrets o modificar contracts.

Implementá catálogo y autorización como intersección server/config/skill. No ejecutar MCP ni leer secrets.

Casos: intersección, unknown, disabled, A no ve tool exclusiva B y `authorize` falla antes del executor.

Verificación: `pytest tests/unit/mcp/test_registry.py tests/security/test_tool_contracts.py -v`.

Commit: `feat: authorize MCP tools by capability`.
