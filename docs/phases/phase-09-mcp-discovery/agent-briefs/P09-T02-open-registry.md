# P09-T02 — Open registry (intersection only)

**Estado:** ready · **Wave:** W8 · **Depends on:** P09-T01 accepted

Eliminar el uso de `KNOWN_TOOLS` como deny-list en autorización. `available()` = intersección `server` (catálogo descubierto) ∩ tenant ∩ skill únicamente. Alinear skills, compiler y validators.

Commit: `feat: authorize discovered MCP tools by intersection`.

## Lectura obligatoria

- [ADR-005](../../../01-architecture/adr/ADR-005-mcp-discovery-and-generic-invoke.md)
- [../TDD.md](../TDD.md)
- [../acceptance-criteria.md](../acceptance-criteria.md) — AC-P09-002–004, AC-P09-009–010

## Archivos exactos e interfaces

**Modificar:**

- `src/ia_mcp/mcp/registry.py` — `available()` intersección pura; conservar `KNOWN_TOOLS` como alias canónico
- `src/ia_mcp/skills/registry.py`
- `src/ia_mcp/skills/appointments.py`
- `src/ia_mcp/evals/validator.py`
- `src/ia_mcp/onboarding/validator.py`
- `src/ia_mcp/agent_runtime/context_compiler.py` — `server=` desde catálogo descubierto → `tool_schemas`

**Tests:**

- `tests/unit/mcp/test_registry.py`
- `tests/unit/skills/test_registry.py`
- `tests/unit/agent/test_context_compiler.py`
- `tests/unit/onboarding/test_validator.py`
- `tests/evals/unit/test_validator.py` _(crear si no existe; hoy validación en `test_dataset.py`)_

Produce `available(server, tenant, skill) -> frozenset[str]` sin filtro deny-list y compiler que expone `CompiledContext.tool_schemas` desde intersección con nombres descubiertos.

## Comportamiento

- `KNOWN_TOOLS` permanece como alias set canónico de appointments para workflows/fakes; **no** filtra `available()`.
- `appointments` skill: pasa nombres desde config/discovery intersectados; no clamp a `KNOWN_TOOLS`.
- `faq` / `human_handoff`: sin tools salvo config explícita.
- Context compiler: argumento `server=` de `available()` = catálogo descubierto (o inyectado en tests), no `KNOWN_TOOLS`.
- Onboarding/evals: no fallar nombre solo por estar fuera de `KNOWN_TOOLS`; seguir fallando overlap allowed∩forbidden y eval allowlist vacía fail-closed si ya existe.

## Exclusiones

- No crear `discovery.py` / `client.py` (P09-T03).
- No modificar `executor.py` salvo imports rotos (P09-T04).
- No condiciones por tenant slug.
- No secret values en fixtures.

## TDD/evidencia

Rojo: tool descubierta allowlisted falla autorización o compiler sigue usando `KNOWN_TOOLS` como `server=`; verde `pytest tests/unit/mcp/test_registry.py tests/unit/skills/test_registry.py tests/unit/agent/test_context_compiler.py tests/unit/onboarding/test_validator.py tests/evals/unit/ -v && pytest tests/security/test_tool_contracts.py -v`. Criterios AC-P09-002–004, AC-P09-009–011. Adjuntar comandos en evidence y commit.
