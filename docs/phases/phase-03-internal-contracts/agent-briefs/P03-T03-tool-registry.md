# P03-T03 — Tool registry

**Estado:** ready  
**Wave:** W2  
**Depends on:** P02-T02

Implementá catálogo y autorización como intersección server/config/skill. No ejecutar MCP ni leer secrets.

Casos: intersección, unknown, disabled, A no ve tool exclusiva B y `authorize` falla antes del executor.

Verificación: `pytest tests/unit/mcp/test_registry.py tests/security/test_tool_contracts.py -v`.

Commit: `feat: authorize MCP tools by capability`.

