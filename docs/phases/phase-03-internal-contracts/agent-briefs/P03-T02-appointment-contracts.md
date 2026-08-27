# P03-T02 — Contratos appointments

**Estado:** ready  
**Wave:** W2  
**Depends on:** P03-T01

## Lectura obligatoria

Plan maestro §28, ADR-003, `../TDD.md`, AC-P03-001–004/006 y Task 2.

## Archivos exactos

Crear `src/ia_mcp/contracts/appointments.py`, `tests/unit/contracts/test_appointments.py` y snapshots de schema. No incorporar API real o storage.

Implementá los modelos y validators exactos del TDD, schema version 1, extra forbid y timezone. `Patient` no exige globalmente id/nombre; esas obligaciones pertenecen a policy/workflow. No incorporar campos de una API real.

Generá snapshots JSON schema y casos de rango invertido, instante naive, extra tenant/credentials, end antes de start y SecretStr.

Verificación: `pytest tests/unit/contracts/test_appointments.py -v && mypy src/ia_mcp/contracts`.

Commit: `feat: define appointment contracts`.
