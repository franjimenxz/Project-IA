# P08-T03 — Preflight y activación

**Estado:** ready · **Depends on:** P08-T02, Fases 4/6/7

Implementá checks, report hash y activation/disable RBAC. No aceptar waiver de aislamiento/security critical.

Probar stale hash, failed check, atomic mapping/state y A unaffected. Commit `feat: gate tenant activation on preflight evidence`.

## Lectura obligatoria

`../TDD.md` preflight/activation, Phase 6/7 reports, G4, AC-P08-005–009 y Task 3.

## Archivos exactos e interfaces

Crear `src/ia_mcp/onboarding/preflight.py`, `activation.py`, report persistence/migration y integration/E2E tests. Consumir package/content hash y check ports; producir immutable PreflightReport y activate/disable commands. No permitir critical waiver.

## TDD/evidencia

Rojo: H1 report activa H2 o failed check; verde `pytest tests/integration/onboarding/test_preflight.py tests/e2e/test_tenant_activation.py tests/security/test_onboarding.py -v`. Adjuntar report hash, RBAC/audit y commit.
