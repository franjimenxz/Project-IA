# P07-T03 — Vista segura de runs

**Estado:** ready · **Depends on:** P07-T02

Exponé JSON y HTML read-only con RBAC/tenant assignment. No agregar botones de tool/mutación ni frontend SPA.

Probar auth, 404 uniforme, escaping, timezone y pagination. Commit `feat: expose secure run investigation view`.

## Lectura obligatoria

`../TDD.md` API/view, security TDD RBAC, AC-P07-003–005, P07-T02 interface y Task 3.

## Archivos exactos e interfaces

Crear `src/ia_mcp/api/routes/admin_runs.py`, `api/auth/admin.py`, `api/templates/run_investigation.html`, API tests. Consumir RunInvestigationQuery; producir GET JSON/HTML read-only. No agregar mutaciones, SPA o bypass de query scope.

## TDD/evidencia

Rojo: JSON/HTML absent, operator B/unauthenticated. Verde `pytest tests/integration/api/test_run_investigation.py tests/security/test_observability.py -v`. Adjuntar HTML sanitizado sintético y commit.
