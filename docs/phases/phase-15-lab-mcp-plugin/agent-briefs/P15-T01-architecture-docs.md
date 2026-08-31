# P15-T01 — Documentación de arquitectura

**Estado:** accepted · **Wave:** W14 · **Depends on:** Fase 13 y Fase 14 accepted

Paquete documental de Fase 15 y ADR-011. Sin código de runtime.

Commit: `docs: unlock Fase 15 lab MCP plugin (ADR-011)`

## Lectura obligatoria

1. `docs/README.md`
2. `docs/00-governance/delegation-protocol.md`
3. [ADR-011](../../../01-architecture/adr/ADR-011-lab-mcp-plugin.md)
4. [../TDD.md](../TDD.md)
5. [../acceptance-criteria.md](../acceptance-criteria.md)

## Archivos permitidos

Solo `docs/**` y el tablero (coordinador).

## Verificación

```text
python scripts/check_docs.py --all docs
python scripts/check_traceability.py
```

Criterio: AC-P15-001 (parte documental).

## Exclusiones

- No implementar `lab_mcp.py` ni tocar `src/`.
- No WhatsApp Cloud ni auth MCP.
