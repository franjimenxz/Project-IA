# P11-T01 — ADR-006 y documentación de fase

**Estado:** in_review · **Wave:** W10 · **Depends on:** P10-T01 aceptada

Documentar el hueco entre el turno conversacional y la maquinaria MCP, y decidir su cierre: contrato de decisión, loop acotado, superficie invocable, errores, aislamiento y observabilidad. Tarea sin código de producción.

Commit: `docs: define conversational tool loop and its boundary`.

## Lectura obligatoria

1. `docs/README.md`
2. `docs/00-governance/delegation-protocol.md`
3. [ADR-005](../../../01-architecture/adr/ADR-005-mcp-discovery-and-generic-invoke.md) y [ADR-003](../../../01-architecture/adr/ADR-003-canonical-contracts-and-workflows.md)
4. `docs/01-architecture/system-tdd.md` §7, §8, §12, §18
5. `docs/00-governance/requirements-catalog.md` (`EXT-007`, BR-007, BR-009, BR-010)
6. Código actual: `src/ia_mcp/agent_runtime/harness.py`, `src/ia_mcp/agent_runtime/models.py`, `src/ia_mcp/api/composition.py`, `src/ia_mcp/mcp/executor.py`, `src/ia_mcp/skills/appointments.py`, `src/ia_mcp/evals/runner.py`, `src/ia_mcp/observability/semconv.py`

## Archivos exactos e interfaces

**Crear:**

- `docs/01-architecture/adr/ADR-006-conversational-tool-loop.md`
- `docs/phases/phase-11-agent-loop/README.md`, `TDD.md`, `implementation-plan.md`, `acceptance-criteria.md`, `test-plan.md`
- `docs/phases/phase-11-agent-loop/agent-briefs/*.md`

**No tocar:**

- `src/**`, `tests/**`, `scripts/**`, `.github/**`
- `docs/00-governance/delegation-board.md`
- `docs/01-architecture/adr/README.md` y `docs/00-governance/master-roadmap.md` (índice y roadmap los actualiza el coordinador)
- ADR-003 y ADR-005: esta decisión no los enmienda

## Interfaces documentadas

El ADR fija estas firmas, que P11-T02 implementa sin desviarse:

```python
type LLMTurnDecision = LLMDecision | ToolCallProposal
async def generate(self, request: LLMRequest) -> LLMTurnDecision: ...
```

`AnswerKind` no cambia. `LLMRequest.tool_results` y `AgentTurnResult.tool_calls` se agregan con default.

## Verificación

Ejecutar y adjuntar salida real:

```text
python scripts/check_docs.py --all docs
python scripts/check_traceability.py
pytest tests/docs -q
ruff check scripts tests/docs
```

Además: cada afirmación de estado actual del ADR cita archivo y línea verificables en el commit base.

Criterio AC-P11-001.

## Exclusiones

- No inventar API, credenciales, autenticación, vendors ni requisitos legales.
- No prometer sin decidir: lo que dependa de un `EXT` o del coordinador se marca como dependencia abierta, no se resuelve por cuenta propia.
- No editar el tablero ni estados de tareas ajenas.
- No PR, no push, no amend de commits ajenos.
