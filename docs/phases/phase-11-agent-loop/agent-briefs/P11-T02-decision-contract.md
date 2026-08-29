# P11-T02 — Contrato de decisión y realimentación

**Estado:** draft · **Wave:** W10 · **Depends on:** P11-T01 aceptada

Permitir que el puerto LLM exprese una tool call y que el resultado de una tool vuelva al request de la iteración siguiente, sin tocar `AnswerKind` ni romper evals.

Commit: `feat: add tool call decision and observation contracts`.

## Lectura obligatoria

1. `docs/README.md`
2. `docs/00-governance/delegation-protocol.md`
3. [ADR-006](../../../01-architecture/adr/ADR-006-conversational-tool-loop.md) §1, §6
4. [../TDD.md](../TDD.md)
5. [../acceptance-criteria.md](../acceptance-criteria.md)
6. Código actual: `src/ia_mcp/agent_runtime/models.py`, `src/ia_mcp/agent_runtime/ports.py`, `src/ia_mcp/evals/runner.py`, `src/ia_mcp/evals/scorers.py`, `src/ia_mcp/mcp/audit.py`, `src/ia_mcp/contracts/errors.py`

## Archivos exactos

**Modificar:**

- `src/ia_mcp/agent_runtime/models.py` — `ToolCallProposal`, `LLMTurnDecision`, `ToolObservation`, `ExecutedToolCall`, campos nuevos con default
- `src/ia_mcp/agent_runtime/ports.py` — retorno de `LLMPort.generate`
- `src/ia_mcp/evals/runner.py` — `observe_turn` prefiere `tool_calls` sobre `tool_names`

**Crear:**

- `tests/unit/agent/test_models.py` (o ampliar el existente)
- `tests/unit/agent/test_tool_observations.py`

**No tocar:**

- `src/ia_mcp/agent_runtime/harness.py` (owner P11-T03)
- `src/ia_mcp/skills/faq.py`, `src/ia_mcp/channels/outbox.py`, `src/ia_mcp/evals/models.py`
- `docs/00-governance/delegation-board.md`

## Interfaces

**Produce:**

```python
type LLMTurnDecision = LLMDecision | ToolCallProposal
async def generate(self, request: LLMRequest) -> LLMTurnDecision: ...
def observation_from(name: str, result: ToolResult[Any]) -> ToolObservation: ...
```

**Consume:**

```python
def sanitize_summary(payload: Mapping[str, object] | None) -> dict[str, object]: ...
```

`AnswerKind` no gana miembros. `LLMRequest.tool_results` y `AgentTurnResult.tool_calls` se agregan con default `()`. `ToolError.upstream_reference` no se copia a ninguna observación.

## Secuencia TDD

1. Rojo: un `LLMPort` que devuelve `ToolCallProposal` no tipa; `LLMRequest` no acepta `tool_results`.
2. Rojo: `observation_from` sobre un `ToolResult` con error filtra `upstream_reference`.
3. Verde: implementación mínima de los tipos y del constructor de observación.
4. Verde: `observe_turn` usa `tool_calls` cuando hay ejecuciones y `tool_names` cuando no.
5. Suite: `pytest tests/unit/agent tests/evals -v`.
6. Estáticos: `ruff check src tests && mypy src/ia_mcp/agent_runtime src/ia_mcp/evals`.

## Verificación

```text
pytest tests/unit/agent/test_models.py tests/unit/agent/test_tool_observations.py -v
pytest tests/evals -v
ruff check src tests
mypy src/ia_mcp/agent_runtime src/ia_mcp/evals
```

`mypy --strict` debe seguir verde en `src/ia_mcp/evals/runner.py` sin editar sus chequeos `exhaustive: Never`.

Criterios AC-P11-002, AC-P11-003, AC-P11-005.

## Exclusiones

- No agregar `"tool_call"` a `AnswerKind` ni a `EvalOutcome`.
- No cambiar el significado de `AgentTurnResult.tool_names`.
- No implementar el loop; esta tarea sólo entrega contrato.
- No pasar secretos ni `upstream_reference` al modelo, logs, traces o fixtures.
- No PR, no push, no editar el tablero.
