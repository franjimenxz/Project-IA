# P08-T02 — Provision y lifecycle

**Estado:** ready · **Depends on:** P08-T01

Implementá provision idempotente en estado disabled, config draft, integrations refs, audit y disable seguro. No ingerir knowledge ni activar.

Probar replay/concurrencia, RBAC, transaction rollback y tenant A intacto. Commit `feat: provision tenant lifecycle idempotently`.

## Lectura obligatoria

`../TDD.md` workflow/lifecycle, ADR-002/004, AC-P08-002/008/009, P08-T01 interface y Task 2.

## Archivos exactos e interfaces

Crear `src/ia_mcp/onboarding/service.py`, `ports.py`, `commands.py`, API/CLI adapter de provision/disable y integration tests. Consumir validated TenantPackage y admin context; producir idempotent provision/disable. No ingerir knowledge ni activar.

## TDD/evidencia

Rojo: replay/concurrent provision duplica tenant/mapping; verde `pytest tests/integration/onboarding/test_provision.py tests/security/test_onboarding.py -v`. Adjuntar transaction/RBAC/audit evidence y commit.
