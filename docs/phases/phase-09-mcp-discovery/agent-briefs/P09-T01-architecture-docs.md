# P09-T01 — Architecture docs (MCP discovery)

**Estado:** accepted-doc · **Wave:** W8 · **Depends on:** Fase 8 aceptada

Documentación únicamente. Definir Fase 9, ADR-005, enmienda ADR-003 y actualizaciones mínimas de arquitectura/governance. Sin código de producto.

Commit: `docs: define MCP discovery instead of closed tool catalog`.

## Lectura obligatoria

- Decisión de producto (prompt de coordinación)
- [ADR-003](../../../01-architecture/adr/ADR-003-canonical-contracts-and-workflows.md)
- [system-tdd.md §13](../../../01-architecture/system-tdd.md)
- [delegation-protocol.md](../../../00-governance/delegation-protocol.md)

## Archivos exactos

**Crear:**

- `docs/phases/phase-09-mcp-discovery/README.md`
- `docs/phases/phase-09-mcp-discovery/TDD.md`
- `docs/phases/phase-09-mcp-discovery/acceptance-criteria.md`
- `docs/phases/phase-09-mcp-discovery/implementation-plan.md`
- `docs/phases/phase-09-mcp-discovery/test-plan.md`
- `docs/phases/phase-09-mcp-discovery/evidence/README.md`
- `docs/phases/phase-09-mcp-discovery/evidence/P09-T01.md`
- `docs/phases/phase-09-mcp-discovery/agent-briefs/README.md`
- `docs/phases/phase-09-mcp-discovery/agent-briefs/P09-T01-architecture-docs.md`
- `docs/phases/phase-09-mcp-discovery/agent-briefs/P09-T02-open-registry.md`
- `docs/phases/phase-09-mcp-discovery/agent-briefs/P09-T03-mcp-client.md`
- `docs/phases/phase-09-mcp-discovery/agent-briefs/P09-T04-generic-executor.md`
- `docs/01-architecture/adr/ADR-005-mcp-discovery-and-generic-invoke.md`

**Modificar (mínimo):**

- `docs/01-architecture/adr/ADR-003-canonical-contracts-and-workflows.md` — nota “Amended by ADR-005”
- `docs/01-architecture/adr/README.md`
- `docs/01-architecture/system-tdd.md` §13
- `docs/01-architecture/component-model.md` — filas MCP
- `docs/01-architecture/security-and-multitenancy.md` — lenguaje allowlist
- `docs/00-governance/assumptions-decisions-dependencies.md` — D-003 nota, D-005
- `docs/00-governance/master-roadmap.md` — W8 / Fase 9
- `docs/00-governance/file-map.md`
- `docs/00-governance/delegation-board.md` — P09-T01–T04
- `docs/README.md` — nueve fases

## Exclusiones

- No modificar `src/`, tests, alembic, fixtures con secret values.
- No abrir PR (coordinador).
- No revertir P05 blocked ni estados accepted de Fases 6–8 / P07-T04.

## Verificación

Documental: briefs T02–T04 `ready`; ADR-005 `accepted`; tablero con T01 `in_review`, T02/T03 `in_progress`, T04 `blocked`.

## Criterios

AC-P09-001

## Evidencia

`docs/phases/phase-09-mcp-discovery/evidence/P09-T01.md`
