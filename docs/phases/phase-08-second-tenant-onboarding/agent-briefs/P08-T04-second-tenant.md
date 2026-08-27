# P08-T04 — Segundo tenant

**Estado:** ready · **Depends on:** P08-T03

Creá tenant B sintético con config/corpus/tools/MCP distintos, ejecutá onboarding, E2E, aislamiento, disable y core diff. No agregar slug B a Core.

Entregá baseline/diff review y evidence AC-P08-001–010. Commit `test: prove second tenant onboarding without core changes`.

## Lectura obligatoria

Todo el TDD/criterios/test plan de Fase 8, onboarding runbook, Definition of Done, G4 y briefs P08-T01–T03.

## Archivos exactos e interfaces

Crear package/evals sintéticos bajo `tenants/fixtures/tenant-b/`, `tests/e2e/test_second_tenant.py`, `scripts/check_tenant_specific_core.py`, runbook/evidence. Sólo config/adapters genéricos pueden modificarse con review; Core queda reservado.

## TDD/evidencia

Rojo: E2E/diff antes de package/activación. Verde: validate→provision→preflight→activate, A/B E2E/security, `python scripts/check_tenant_specific_core.py --base <hash registrado>`, disable/rollback. Entregar AC-P08-001–010, baseline hash, diff reasoning y commit.
