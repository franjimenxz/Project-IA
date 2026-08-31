# P14-T03 — FAQ anuncia herramientas de lectura

**Estado:** accepted · **Wave:** W13 · **Depends on:** Fase 12 accepted

`FAQSkill.allowed_tools` deja de ignorar `config` y anuncia la intersección de `enabled_tools` con `{appointments.search, appointments.get}`. `ContextCompiler` toma el allowlist tenant de `config.enabled_tools` y acepta un catálogo servidor de proceso (`frozenset[str]`).

Commit: `feat: announce FAQ read tools from enabled_tools (P14-T03)`

## Lectura obligatoria

1. `docs/README.md`
2. `docs/00-governance/delegation-protocol.md`
3. [ADR-006](../../../01-architecture/adr/ADR-006-conversational-tool-loop.md)
4. [../TDD.md](../TDD.md)
5. [../acceptance-criteria.md](../acceptance-criteria.md) (AC-P14-006, AC-P14-007, AC-P14-010)
6. [../test-plan.md](../test-plan.md)
7. Código: `src/ia_mcp/skills/faq.py`, `src/ia_mcp/skills/appointments.py` (`configured_tool_allowlist`, no copiar mutaciones), `src/ia_mcp/agent_runtime/context_compiler.py`, `src/ia_mcp/mcp/registry.py`, `tests/unit/skills/test_faq.py`, `tests/unit/agent/test_context_compiler.py`

## Archivos permitidos

**Modificar:**

- `src/ia_mcp/skills/faq.py`
- `src/ia_mcp/agent_runtime/context_compiler.py`
- `tests/unit/skills/test_faq.py`
- `tests/unit/agent/test_context_compiler.py`

**Crear (si hace falta isolation dedicado):**

- `tests/security/test_faq_tools_tenant_isolation.py`

**No tocar:**

- `src/ia_mcp/api/composition.py`
- mutaciones (`create` / `cancel` / `reschedule` / `confirm`)
- `docs/00-governance/delegation-board.md`

## Interfaces

```python
def allowed_tools(self, config: TenantConfig) -> frozenset[ToolName]: ...
```

FAQ:

```python
_READ = frozenset({ToolName("appointments.search"), ToolName("appointments.get")})
return frozenset(ToolName(name) for name in config.enabled_tools if name in _READ)
```

`test_faq_exposes_no_tools` hoy afirma `allowed_tools == frozenset()` con config sin tools. Ese caso **sigue** vacío. Agregar: `enabled_tools` con search+create → solo search.

Compiler: el término tenant de `tool_registry.available(...)` es `config.enabled_tools`, no `self._tenant_tools.get(...)`.

`server_tools` del constructor acepta `Mapping[UUID, frozenset[str]] | frozenset[str] | None`. Un `frozenset` es el catálogo de todo el proceso (T04 lo usará). `None` o clave ausente = vacío. Los tests actuales que pasan un `Mapping` no cambian de semántica.

Agregar test: FAQ + `enabled_tools={"appointments.search"}` + `server_tools=frozenset({"appointments.search"})` → `tool_schemas` incluye search.

Los tests de appointments que ya ponen el mismo set en `enabled_tools` y `tenant_tools` deben seguir verdes.

## TDD

1. Rojo en `test_faq.py`: search+create → solo search.
2. Rojo en compiler: FAQ + `enabled_tools` + server catalog → `tool_schemas` incluye search.
3. Implementación mínima.
4. Verde. Isolation: tenant A y B con `enabled_tools` distintos no se mezclan.

## Verificación

```text
pytest tests/unit/skills/test_faq.py tests/unit/agent/test_context_compiler.py -v
ruff check src/ia_mcp/skills/faq.py src/ia_mcp/agent_runtime/context_compiler.py tests/unit/skills/test_faq.py tests/unit/agent/test_context_compiler.py
```

Criterios: AC-P14-006, AC-P14-007, AC-P14-010.

## Exclusiones

- No cablear composition (T04).
- No anunciar tools de mutación desde FAQ.
- No editar el tablero.
