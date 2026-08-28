# P09-T03 — MCP discovery + SSE client

**Estado:** ready · **Wave:** W8 · **Depends on:** P09-T01 accepted

Implementar discovery (`tools/list`) e invocación (`tools/call`) contra MCP SSE (FastMCP: `/sse` + `/messages/?session_id=`). Fake in-process para CI; E2E opcional con `MCP_SSE_URL`.

Commit: `feat: add MCP discovery and SSE client`.

## Lectura obligatoria

- [ADR-005](../../../01-architecture/adr/ADR-005-mcp-discovery-and-generic-invoke.md)
- [../TDD.md](../TDD.md)
- [security-and-multitenancy.md](../../../01-architecture/security-and-multitenancy.md) — host allowlist

## Archivos exactos e interfaces

**Crear:**

- `src/ia_mcp/mcp/discovery.py`
- `src/ia_mcp/mcp/client.py`
- `tests/unit/mcp/test_discovery.py`
- `tests/unit/mcp/test_client.py`
- `tests/unit/mcp/fakes/sse_server.py` _(fake in-process; sin IP LAN en CI)_

**Opcional (skip por defecto):**

- `tests/e2e/test_mcp_discovery.py` — solo si `MCP_SSE_URL` definida

Produce `list_tools(tenant, target) -> DiscoveredToolCatalog` y `call_tool(tenant, target, name, arguments) -> ToolResult`. Consume `McpTarget` (endpoint, auth_reference, allowed_tools) y `HostAllowlist` para validación fail-closed.

## Exclusiones

- No modificar `registry.py` lógica de intersección (P09-T02).
- No modificar `executor.py` dispatch (P09-T04).
- No hardcodear `192.168.1.247` ni hosts de producción en tests obligatorios.
- No secret values en código, docs ni fixtures.

## TDD/evidencia

Rojo: discovery/client ausentes o host no allowlisted no rechazado; verde `pytest tests/unit/mcp/test_discovery.py tests/unit/mcp/test_client.py -v && mypy src/ia_mcp/mcp/discovery.py src/ia_mcp/mcp/client.py`. E2E opcional: `MCP_SSE_URL=http://127.0.0.1:8765 pytest -m e2e tests/e2e/test_mcp_discovery.py -v`. Criterios AC-P09-005, AC-P09-006, AC-P09-012. Adjuntar salida y commit.
