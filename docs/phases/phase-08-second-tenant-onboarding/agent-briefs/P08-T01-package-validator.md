# P08-T01 — Tenant package validator

**Estado:** ready · **Wave:** W7

Implementá schemas/loader/validate CLI para tenant/config/policies/knowledge/integrations/evals. No persistir ni resolver secret values.

Probar extra fields, secret literals, checksum, channel duplicate, skills/tools y schema version. Commit `feat: validate declarative tenant packages`.

## Lectura obligatoria

`../TDD.md` package/preflight, security TDD, AC-P08-001/003/004, file map y Task 1.

## Archivos exactos e interfaces

Crear `src/ia_mcp/onboarding/models.py`, `loader.py`, `validator.py`, `cli.py`, JSON schema y `tests/unit/onboarding/*`. No persistir, resolver secrets o versionar PDFs. Produce `validate_package(Path) -> ValidationReport`.

## TDD/evidencia

Rojo: secret literal y invalid cross-file config; verde `pytest tests/unit/onboarding -v && python -m ia_mcp.onboarding validate tenants/fixtures/tenant-b`. Adjuntar report redacted/schema y commit.
