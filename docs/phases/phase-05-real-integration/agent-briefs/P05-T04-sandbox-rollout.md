# P05-T04 — Sandbox y rollout

**Estado:** blocked · **Depends on:** P05-T03

Ejecutá contract/E2E en sandbox dedicado con datos sintéticos. No usar pacientes reales ni guardar secrets/payloads crudos.

Entregá evidence, reconciliación, canary, abort/rollback y sign-offs. Commit `test: verify institutional MCP in sandbox`.

## Lectura obligatoria

P05-T01–T03 accepted, `../TDD.md`, `../acceptance-criteria.md`, test plan, rollout policy, security/observability TDDs.

## Archivos exactos

Crear `tests/sandbox/<institution>/test_appointments.py`, `docs/runbooks/<institution>-activation.md` y evidence reports; modificar sólo tenant integration config/feature flag autorizado. No versionar cassettes o datos reales.

## Interfaces, TDD y gate

Consume adapter público y sandbox. Empezar reads, luego mutaciones sintéticas con cleanup/reconciliation e idempotency; ejecutar `pytest -m sandbox tests/sandbox/<institution> -v` y E2E tenant dedicado. Entregar AC-P05-001–010, canary/abort/rollback probado y sign-offs para G4.
