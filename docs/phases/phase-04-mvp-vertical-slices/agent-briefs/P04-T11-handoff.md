# P04-T11 — Human handoff

**Estado:** ready · **Wave:** W4 · **Depends on:** P04-T04, P04-T06

Implementá modelos, transacción ownership+handoff+outbox, FakeHandoffAdapter y guard del Harness. No diseñar UI de operador.

Resumen estructurado y sanitizado; reason tipado; business key idempotente. Probar explicit/policy/error triggers, duplicate, provider down, mutation blocked y operator tenant isolation.

Criterios AC-P04-040–046. Commit `feat: transfer conversations to human operators`.

## Lectura obligatoria

System TDD §15, security/data TDDs, `../TDD.md` §4, criterios 4.4 y Task 11.

## Archivos exactos

Crear `src/ia_mcp/handoff/models.py`, `ports.py`, `service.py`, `adapters/fake.py`, migración `0005_handoff.py`, unit/integration/E2E tests; modificar sólo el guard de Harness. No crear UI/operator provider real.

## Interfaces y TDD

Produce `HandoffService.create(TenantContext, HandoffRequest) -> HandoffResult`. Rojo: atomic ownership+handoff/replay; verde: `pytest tests/unit/handoff tests/integration/mvp/test_handoff.py tests/e2e/test_handoff.py tests/security/test_tenant_isolation.py -v`. Evidence de payload sanitizado y provider-down outbox.
