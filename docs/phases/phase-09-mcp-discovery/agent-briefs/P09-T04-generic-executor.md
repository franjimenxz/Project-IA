# P09-T04 — Generic executor dispatch

**Estado:** ready · **Wave:** W8 · **Depends on:** P09-T02, P09-T03 accepted

Extender executor: si el nombre es canónico `appointments.*` y la capability está cableada, mantener dispatch actual; en caso contrario, invocar via cliente MCP genérico tras autorización.

Commit: `feat: generic MCP tool invocation in executor`.

## Lectura obligatoria

- [ADR-005](../../../01-architecture/adr/ADR-005-mcp-discovery-and-generic-invoke.md)
- [../TDD.md](../TDD.md)
- Brief P03-T05 (executor baseline)

## Archivos exactos

**Modificar:**

- `src/ia_mcp/mcp/executor.py`

**Tests:**

- `tests/unit/mcp/test_executor.py`
- `tests/security/test_tool_contracts.py` _(solo casos nuevos si hace falta)_

## Comportamiento

```text
authorize(tool, discovered, tenant, skill)
→ resolver + host allowlist (fail-closed)
→ if tool in KNOWN_TOOLS appointments.* AND AppointmentCapability wired:
      existing capability/workflow dispatch
  else if tool in authorized intersection:
      generic McpTransportClient.call_tool(...)
  else:
      ForbiddenTool (sin invocar)
```

No reescribir dominio de Fases 6–8 (workflows, scheduling, onboarding activation).

## Exclusiones

- No cambiar firma pública de workflows.
- No inventar REST médico.
- No relajar host allowlist.
- No tocar `discovery.py` / `client.py` salvo wiring DI.

## TDD — rojo / verde

**Rojo:**

```bash
pytest tests/unit/mcp/test_executor.py::test_generic_client_called_for_non_canonical_authorized_tool -v
pytest tests/unit/mcp/test_executor.py::test_canonical_appointment_still_uses_capability -v
pytest tests/unit/mcp/test_executor.py::test_unauthorized_tool_does_not_invoke_client -v
```

**Verde:**

```bash
pytest tests/unit/mcp/test_executor.py tests/security/test_tool_contracts.py -v
mypy src/ia_mcp/mcp/executor.py
```

## Criterios

AC-P09-007, AC-P09-008, AC-P09-012

## Evidencia

`docs/phases/phase-09-mcp-discovery/evidence/P09-T04.md`
