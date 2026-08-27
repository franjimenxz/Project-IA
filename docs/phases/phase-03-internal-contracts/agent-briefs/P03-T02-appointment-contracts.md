# P03-T02 — Contratos appointments

**Estado:** ready  
**Wave:** W2  
**Depends on:** P03-T01

Implementá los modelos y validators exactos del TDD, schema version 1, extra forbid y timezone. No incorporar campos de una API real.

Generá snapshots JSON schema y casos de rango invertido, instante naive, extra tenant/credentials, end antes de start y SecretStr.

Verificación: `pytest tests/unit/contracts/test_appointments.py -v && mypy src/ia_mcp/contracts`.

Commit: `feat: define appointment contracts`.

