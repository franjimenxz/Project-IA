# P11-T03 — Loop acotado en el harness

**Estado:** ready · **Wave:** W10 · **Depends on:** P11-T02 aceptada

Ejecutar en `AgentHarness` un loop acotado que consuma el `ToolExecutor` cableado en Fase 10, con superficie invocable fail-closed, límites duros y errores tipados.

Commit: `feat: run bounded tool loop in agent harness`.

## Lectura obligatoria

1. `docs/README.md`
2. `docs/00-governance/delegation-protocol.md`
3. [ADR-006](../../../01-architecture/adr/ADR-006-conversational-tool-loop.md) §2–§5, §7
4. [ADR-005](../../../01-architecture/adr/ADR-005-mcp-discovery-and-generic-invoke.md) y [ADR-003](../../../01-architecture/adr/ADR-003-canonical-contracts-and-workflows.md)
5. [../TDD.md](../TDD.md) y [../acceptance-criteria.md](../acceptance-criteria.md)
6. Código actual: `src/ia_mcp/agent_runtime/harness.py`, `src/ia_mcp/mcp/executor.py`, `src/ia_mcp/api/composition.py`, `src/ia_mcp/skills/faq.py`, `src/ia_mcp/mcp/client.py`, `src/ia_mcp/performance/models.py`

## Archivos exactos

**Modificar:**

- `src/ia_mcp/agent_runtime/harness.py` — loop, límites, superficie invocable, mapeo de errores
- `src/ia_mcp/api/composition.py` — pasar la factory de executors y los límites al harness

**Crear:**

- `tests/unit/agent/test_harness_loop.py`
- `tests/unit/agent/test_harness_loop_errors.py`
- `tests/unit/agent/test_turn_tool_surface.py`

**No tocar:**

- `src/ia_mcp/mcp/executor.py`, `src/ia_mcp/mcp/registry.py` (autorización ya cerrada en Fase 9)
- `src/ia_mcp/workflows/**`, `src/ia_mcp/scheduling/**`
- `src/ia_mcp/configuration/models.py` (escalar si hace falta un campo de superficie o de límites)
- `src/ia_mcp/observability/semconv.py` (escalar si hace falta un atributo nuevo)
- `docs/00-governance/delegation-board.md`

## Interfaces

**Consume:**

```python
async def for_tenant(self, tenant: TenantContext, config: TenantConfig, skill: str) -> ToolExecutor: ...
async def execute(self, tenant: TenantContext, run_id: UUID, call: ToolCall, carrier: MutableMapping[str, str] | None = None) -> ToolResult[Any]: ...
```

**Produce:**

```python
class AgentHarness:
    def __init__(self, *, ..., executors: TenantToolExecutors | None = None,
                 max_tool_iterations: int = 4, turn_deadline_seconds: float = 30.0) -> None: ...
```

Con `executors=None` o `max_tool_iterations=0` el turno vuelve a ser exactamente el actual: una sola llamada al modelo.

## Comportamiento

```text
iteración < max_tool_iterations y deadline vigente:
  decision terminal            → policy.apply → finish
  ToolCallProposal:
    par (name, arguments) repetido      → finish insufficient (tool_call_repeated)
    name fuera de invocable_en_turno    → observación forbidden; iteración += 1
    caso contrario                      → executor.execute → observación; iteración += 1
iteraciones agotadas → finish insufficient (tool_budget_exhausted)
deadline vencido     → finish insufficient (turn_deadline_exceeded)
dos forbidden        → finish handoff
tenant_isolation_violation → aborto sin realimentar; run failed
```

`invocable_en_turno` es `discovered ∩ tenant ∩ skill ∩ turn`. El término `turn` excluye toda tool canónica cuyo dispatch exija idempotency key (`src/ia_mcp/mcp/executor.py:303`, `:310`, `:319`, `:326`) y excluye toda tool descubierta no declarada. Sin catálogo cerrado ni condiciones por slug.

## Secuencia TDD

1. Rojo: un LLM fake que devuelve `ToolCallProposal` no ejecuta nada y el turno responde como si no hubiera tools.
2. Rojo: la propuesta de una tool que exige idempotency key alcanza la capability.
3. Verde: loop mínimo con ejecución, observación y segunda llamada al modelo.
4. Verde: límites, deadline, superficie fail-closed y mapeo de errores.
5. Suite: `pytest tests/unit/agent tests/unit/mcp -v`.
6. Estáticos: `ruff check src tests && mypy src/ia_mcp/agent_runtime src/ia_mcp/api`.

## Verificación

```text
pytest tests/unit/agent/test_harness_loop.py tests/unit/agent/test_harness_loop_errors.py tests/unit/agent/test_turn_tool_surface.py -v
pytest tests/unit/agent/test_harness.py tests/unit/mcp/test_executor.py -v
ruff check src tests
mypy src/ia_mcp/agent_runtime src/ia_mcp/api
```

Criterios AC-P11-004, AC-P11-006, AC-P11-007, AC-P11-008, AC-P11-009, AC-P11-012.

## Restricciones

- Ninguna mutación desde el loop; el workflow engine no se invoca desde el turno.
- El executor se construye por turno desde el `TenantContext` del turno; no se cachea entre tenants.
- Sin capa de retry propia en el harness.
- Sin `if tenant_slug == "…"` en Core.
- Sin secretos ni `upstream_reference` en prompts, logs, traces o fixtures.

## Bloqueos

Si el loop necesita un campo de `TenantConfig` o un atributo de `semconv`, se escala según `docs/00-governance/delegation-protocol.md`; no se altera el contrato compartido para evitar el bloqueo.

## Exclusiones

- No PR, no push, no amend de commits ajenos, no editar el tablero.
