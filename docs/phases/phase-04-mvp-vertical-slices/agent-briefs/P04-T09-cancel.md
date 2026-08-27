# P04-T09 — Cancelación

**Estado:** ready · **Wave:** W4 · **Depends on:** P04-T08

Implementá workflow get→confirm→cancel usando contratos; no editar create/reschedule. Already cancelled es éxito idempotente; ID de B bajo A no revela existencia.

Probar política disabled, confirm negada, replay, conflict, timeout incierto y cross-tenant. Criterios AC-P04-030–032, 038.

Verificación lifecycle/security suites. Commit `feat: cancel appointments idempotently`.

