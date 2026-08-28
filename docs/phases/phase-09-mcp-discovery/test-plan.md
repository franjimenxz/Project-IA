# Test Plan — Fase 9

| Suite | Comando | Criterios |
|---|---|---|
| Registry intersection | `pytest tests/unit/mcp/test_registry.py -v` | AC-P09-002–004 |
| Skills registry | `pytest tests/unit/skills/test_registry.py -v` | AC-P09-002, AC-P09-010 |
| Context compiler | `pytest tests/unit/agent/test_context_compiler.py -v` | AC-P09-009 |
| Onboarding validator | `pytest tests/unit/onboarding/test_validator.py -v` | AC-P09-010 |
| Eval validator | `pytest tests/unit/evals/test_validator.py -v` | AC-P09-010 |
| MCP discovery/client | `pytest tests/unit/mcp/test_discovery.py tests/unit/mcp/test_client.py -v` | AC-P09-005, AC-P09-006 |
| Executor | `pytest tests/unit/mcp/test_executor.py -v` | AC-P09-007, AC-P09-008 |
| Tool contracts security | `pytest tests/security/test_tool_contracts.py -v` | AC-P09-004, AC-P09-011 |
| Optional E2E SSE | `pytest -m e2e tests/e2e/test_mcp_discovery.py -v` | AC-P09-005 (skip sin `MCP_SSE_URL`) |
| Phase regression | `pytest tests/unit/mcp tests/unit/skills tests/unit/agent/test_context_compiler.py -v` | AC-P09-012 |

El fake in-process de T03 es obligatorio en CI. No depender de `192.168.1.247` ni hosts LAN no versionados.
