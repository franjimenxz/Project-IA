# P15-T03 — Runtime adaptado al MCP enchufado

**Estado:** blocked · **Wave:** W14 · **Depends on:** P15-T02 accepted

El turno de laboratorio anuncia e invoca las tools que el tenant habilitó (catálogo descubierto). Con endpoint allowlisted, el executor usa SSE también para nombres canónicos. Sin endpoint, el fake y la regla de lectura de ADR-006 se mantienen.

Commit: `feat: adapt lab turn to plugged MCP catalog (P15-T03)`

## Lectura obligatoria

1. `docs/README.md`
2. `docs/00-governance/delegation-protocol.md`
3. [ADR-011](../../../01-architecture/adr/ADR-011-lab-mcp-plugin.md)
4. [../TDD.md](../TDD.md)
5. [../acceptance-criteria.md](../acceptance-criteria.md) (AC-P15-006 a AC-P15-008)
6. Código: `src/ia_mcp/onboarding/lab_mcp.py` (ya en main vía T02), `src/ia_mcp/skills/faq.py`, `src/ia_mcp/agent_runtime/harness.py`, `src/ia_mcp/agent_runtime/context_compiler.py`, `src/ia_mcp/mcp/executor.py`, `src/ia_mcp/mcp/client.py`, `src/ia_mcp/api/composition.py`

## Archivos permitidos

**Modificar:**

- `src/ia_mcp/skills/faq.py`
- `src/ia_mcp/agent_runtime/harness.py`
- `src/ia_mcp/agent_runtime/context_compiler.py`
- `src/ia_mcp/mcp/executor.py`
- `src/ia_mcp/mcp/client.py`
- `src/ia_mcp/api/composition.py`
- `tests/unit/skills/test_faq.py`
- `tests/unit/agent/test_turn_tool_surface.py` y/o tests nuevos en `tests/unit/agent/`
- `tests/unit/mcp/test_executor.py`
- `tests/unit/mcp/test_client.py` si cambia `list_tools`
- `tests/unit/api/test_composition.py`
- `tests/unit/agent/test_context_compiler.py` solo si el flag lo exige
- `tests/security/test_faq_tools_tenant_isolation.py` si deja de valer AC-P14-006

**No tocar:**

- `src/ia_mcp/onboarding/lab_package.py`
- `src/ia_mcp/api/templates/`
- `src/ia_mcp/api/routes/instituciones.py`
- `docs/00-governance/delegation-board.md`
- WhatsApp Cloud, P05, secretos

## Interfaces

`allowed_tools(self, config)` y `invocable_on_turn(name, declared_for_turn=frozenset())` son el contrato.

```python
# faq.py
def allowed_tools(self, config: TenantConfig) -> frozenset[ToolName]:
    return frozenset(ToolName(name) for name in config.enabled_tools)

# harness.py
if not invocable_on_turn(decision.name, declared_for_turn=frozenset(tool_names)):
    ...
# si not hits and not config.enabled_tools: cortar como hoy
# si executed ok y decision.kind == "answer" y text: aceptar sin exigir cites

# context_compiler.py
def __init__(..., mirror_tenant_tools: bool = False): ...
# server = catalog | config.enabled_tools  solo si mirror_tenant_tools

# client.py
async def list_tools(..., intersect_allowed: bool = True) -> DiscoveredToolCatalog: ...

# executor._dispatch
# si target.endpoint allowlisted: transport.call_tool para cualquier name
# si no hay endpoint: KNOWN_TOOLS → capability (igual que hoy)

# composition.build_runtime
# endpoints = {**load_lab_mcp_endpoints(packages_dir), **mcp_endpoints_from(environ)}
# ContextCompiler(..., mirror_tenant_tools=True)
```

Cero ramas por slug. Cero auth inventada en el cliente SSE.

Los tests existentes de mutación canónica **sin** `tool_names` anunciados deben seguir en `forbidden`.

## TDD

1. Rojo: FAQ sigue recortando create; create no anunciado forbidden (debe seguir); con endpoint el search sigue yendo al fake.
2. Verde: AC-P15-006–008.
3. Isolation A/B.

## Verificación

```text
pytest tests/unit/skills/test_faq.py tests/unit/agent/test_turn_tool_surface.py tests/unit/mcp/test_executor.py tests/unit/api/test_composition.py tests/security/test_faq_tools_tenant_isolation.py tests/security/test_tool_loop_isolation.py -v
ruff check src/ia_mcp/skills/faq.py src/ia_mcp/agent_runtime/harness.py src/ia_mcp/agent_runtime/context_compiler.py src/ia_mcp/mcp/executor.py src/ia_mcp/mcp/client.py src/ia_mcp/api/composition.py
```

Criterios: AC-P15-006 a AC-P15-008. AC-P14-006 queda enmendado por ADR-011 para el lab: FAQ ya no recorta create si está en `enabled_tools`.

## Exclusiones

- No editar el form ni el tablero.
- No inventar Bearer hacia el MCP.
- No activar WhatsApp Cloud.
