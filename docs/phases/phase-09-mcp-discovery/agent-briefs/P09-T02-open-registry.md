# P09-T02 — Open registry (intersection only)

**Estado:** ready · **Wave:** W8 · **Depends on:** P09-T01 accepted

Eliminar el uso de `KNOWN_TOOLS` como deny-list en autorización. `available()` = intersección discovered/server ∩ tenant ∩ skill únicamente. Alinear skills, compiler y validators.

Commit: `feat: authorize discovered MCP tools by intersection`.

## Lectura obligatoria

- [ADR-005](../../../01-architecture/adr/ADR-005-mcp-discovery-and-generic-invoke.md)
- [../TDD.md](../TDD.md)
- [../acceptance-criteria.md](../acceptance-criteria.md) — AC-P09-002–004, AC-P09-009–010

## Archivos exactos

**Modificar:**

- `src/ia_mcp/mcp/registry.py`
- `src/ia_mcp/skills/registry.py`
- `src/ia_mcp/skills/appointments.py`
- `src/ia_mcp/evals/validator.py`
- `src/ia_mcp/onboarding/validator.py`
- `src/ia_mcp/agent_runtime/context_compiler.py`

**Tests:**

- `tests/unit/mcp/test_registry.py`
- `tests/unit/skills/test_registry.py`
- `tests/unit/agent/test_context_compiler.py`
- `tests/unit/onboarding/test_validator.py`
- `tests/unit/evals/test_validator.py` _(crear si no existe)_

## Comportamiento

- `KNOWN_TOOLS` permanece como alias set canónico de appointments para workflows/fakes; **no** filtra `available()`.
- `appointments` skill: pasa nombres desde config/discovery intersectados; no clamp a `KNOWN_TOOLS`.
- `faq` / `human_handoff`: sin tools salvo config explícita.
- Context compiler: `server=` desde catálogo descubierto o catálogo inyectado en tests, no desde `KNOWN_TOOLS`.
- Onboarding/evals: no fallar nombre solo por estar fuera de `KNOWN_TOOLS`; seguir fallando overlap allowed∩forbidden y eval allowlist vacía fail-closed si ya existe.

## Exclusiones

- No crear `discovery.py` / `client.py` (P09-T03).
- No modificar `executor.py` salvo imports rotos (P09-T04).
- No condiciones por tenant slug.
- No secret values en fixtures.

## TDD — rojo / verde

**Rojo:**

```bash
pytest tests/unit/mcp/test_registry.py::test_available_includes_discovered_non_canonical_name -v
pytest tests/unit/onboarding/test_validator.py::test_accepts_tool_name_outside_known_tools -v
```

**Verde:**

```bash
pytest tests/unit/mcp/test_registry.py tests/unit/skills/test_registry.py tests/unit/agent/test_context_compiler.py tests/unit/onboarding/test_validator.py tests/unit/evals/ -v
pytest tests/security/test_tool_contracts.py -v
```

## Criterios

AC-P09-002, AC-P09-003, AC-P09-004, AC-P09-009, AC-P09-010, AC-P09-011

## Evidencia

`docs/phases/phase-09-mcp-discovery/evidence/P09-T02.md`
