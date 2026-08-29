# P11-T04 — Aislamiento, auditoría y trazas del loop

**Estado:** draft · **Wave:** W10 · **Depends on:** P11-T03 aceptada

Probar que el loop no cruza el boundary de tenant y dejar el turno reconstruible: `agent.run` como span raíz, una `llm.generate` por iteración y `run_id` del turno en cada `ToolAuditEvent`.

Commit: `feat: isolate and instrument the conversational tool loop`.

## Lectura obligatoria

1. `docs/README.md`
2. `docs/00-governance/delegation-protocol.md`
3. [ADR-006](../../../01-architecture/adr/ADR-006-conversational-tool-loop.md) §8, §9
4. [ADR-002](../../../01-architecture/adr/ADR-002-tenant-context-and-isolation.md)
5. `docs/01-architecture/observability-strategy.md` y `docs/01-architecture/security-and-multitenancy.md`
6. [../TDD.md](../TDD.md) y [../test-plan.md](../test-plan.md)
7. Código actual: `src/ia_mcp/observability/semconv.py`, `src/ia_mcp/observability/propagation.py`, `src/ia_mcp/mcp/audit.py`, `src/ia_mcp/observability/adapters/sqlalchemy_run_query.py`

## Archivos exactos

**Modificar:**

- `src/ia_mcp/agent_runtime/harness.py` — emitir `agent.run` y `llm.generate`, propagar `run_id` al executor

**Crear:**

- `tests/security/test_tool_loop_isolation.py`
- Casos de trazas en `tests/security/test_observability.py`

**No tocar:**

- `src/ia_mcp/observability/semconv.py` — agregar un atributo requiere coordinación de owners
- `src/ia_mcp/observability/adapters/**` y `alembic/**` — el sink durable es dependencia abierta, no parte de esta tarea
- `docs/00-governance/delegation-board.md`

## Interfaces

**Consume:**

```python
@contextmanager
def start_span(
    name: str,
    *,
    attributes: Mapping[str, object] | None = None,
    links: Sequence[tuple[str, str]] | None = None,
) -> Iterator[SpanRecord]: ...

def span_attributes(raw: Mapping[str, object]) -> dict[str, object]: ...
```

El índice de iteración no se pasa como atributo: `ALLOWED_SPAN_ATTRIBUTES` no lo contiene y `span_attributes` descarta en silencio toda clave fuera del set (`src/ia_mcp/observability/semconv.py:29-47`, `:102`). El conteo se deriva de la cardinalidad de spans hijos.

## Pruebas negativas obligatorias

| Escenario | Resultado esperado |
|---|---|
| Tenant A propone una tool descubierta sólo en el MCP de tenant B | `forbidden` sin invocar transporte; auditoría `allowed=False` |
| Dos turnos concurrentes de tenants distintos | Executors distintos, construidos cada uno desde su `TenantContext`; sin observaciones cruzadas |
| Tenant A amplía su allowlist | La superficie invocable de tenant B no cambia |
| MCP devuelve `tenant_isolation_violation` | Aborto sin realimentar al modelo; run `failed`; auditoría crítica |

## Secuencia TDD

1. Rojo: no existe prueba de que el loop respete el boundary; `agent.run` y `llm.generate` no se emiten en un turno.
2. Rojo: `ToolAuditEvent.run_id` no coincide con el `run_id` del turno.
3. Verde: spans del turno y propagación del `run_id`.
4. Verde: suite negativa multi-tenant completa.
5. Suite: `pytest tests/security tests/unit/agent -v`.
6. Estáticos: `ruff check src tests && mypy src/ia_mcp/agent_runtime`.

## Verificación

```text
pytest tests/security/test_tool_loop_isolation.py tests/security/test_observability.py -v
pytest tests/unit/agent tests/unit/mcp/test_executor.py -v
ruff check src tests
mypy src/ia_mcp/agent_runtime
```

Un turno con una tool ejecutada emite `agent.run`, dos `llm.generate`, un `tool.execute` y un `mcp.resolve`.

Criterios AC-P11-010, AC-P11-011.

## Restricciones

- Sin prompts, completions, payloads crudos, DNI, email, teléfono ni auth headers en spans, métricas o logs.
- `tenant_id` sólo como identificador opaco; `run_id` nunca como label de métrica.
- `TenantContext` en todo boundary del loop.

## Evidencia requerida

- commit;
- comandos y resultados;
- criterios cubiertos;
- archivos modificados;
- residual explícito: las ejecuciones de tool del loop no aparecen en `RunInvestigation.tools` hasta que exista sink durable.

## Exclusiones

- No PR, no push, no editar el tablero.
