# P04-T12 — Scheduler y recordatorios

**Estado:** ready · **Wave:** W5 · **Depends on:** P04-T08, P04-T10

Implementá jobs persistentes, Clock port, claim lease, eligibility check, outbox y route al confirm workflow. No usar sleep real ni estado sólo Redis.

Probar timezone Buenos Aires, 48h/default y config distinta, reschedule que incrementa `schedule_version` y vuelve stale el claim anterior, confirmed/cancelled skip, duplicate dispatch, worker restart, channel failure y tenant A/B.

Criterios AC-P04-050–058. Commit `feat: schedule idempotent appointment reminders`.

## Lectura obligatoria

System TDD §16–17, data model ScheduledJob, ADR-004, `../TDD.md` §5, criterios AC-P04-050–058 y Task 12.

## Archivos exactos

Crear `src/ia_mcp/scheduling/models.py`, `ports.py`, `service.py`, `worker.py`, migración `0006_scheduling.py` y unit/integration/E2E tests. No usar sleep real, cron externo o Redis autoritativo.

## Interfaces y TDD

Produce `ReminderScheduler.upsert/cancel`, `Clock`, `JobWorker.claim/dispatch`; consume appointment events, ChannelAdapter y confirm workflow. Rojo: fecha 48h y stale-version tests; verde: `pytest tests/unit/scheduling tests/integration/mvp/test_scheduler.py tests/e2e/test_reminders.py tests/resilience/test_scheduler.py -v`. Evidence AC-P04-050–058.
