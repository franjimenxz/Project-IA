# P04-T12 — Scheduler y recordatorios

**Estado:** ready · **Wave:** W5 · **Depends on:** P04-T08, P04-T10

Implementá jobs persistentes, Clock port, claim lease, eligibility check, outbox y route al confirm workflow. No usar sleep real ni estado sólo Redis.

Probar timezone Buenos Aires, 48h/default y config distinta, confirmed/cancelled skip, duplicate dispatch, worker restart, channel failure y tenant A/B.

Criterios AC-P04-050–057. Commit `feat: schedule idempotent appointment reminders`.

