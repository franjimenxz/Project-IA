# Tablero de delegación

**Estado del tablero:** active  
**Regla:** el estado de ejecución de este tablero prevalece sobre el estado documental del brief.

## Significado de estados

- `ready`: puede delegarse ahora.
- `blocked`: espera tareas o dependencias listadas.
- `in_progress`: asignada a un único agente.
- `in_review`: implementación entregada, pendiente de dos revisiones.
- `accepted`: integrada y con evidencia.

Un brief `ready` significa que su especificación está completa; no habilita ejecución si este tablero indica `blocked`.

## Cola completa

| Tarea | Wave | Estado inicial | Depende de | Brief |
|---|---|---|---|---|
| P01-T01 | W0 | accepted | — | [brief](../phases/phase-01-functional-specification/agent-briefs/P01-T01-document-validator.md) |
| P01-T02 | W0 | accepted | P01-T01 | [brief](../phases/phase-01-functional-specification/agent-briefs/P01-T02-traceability-checker.md) |
| P01-T03 | W0 | accepted | P01-T01, P01-T02 | [brief](../phases/phase-01-functional-specification/agent-briefs/P01-T03-docs-ci.md) |
| P02-T01 | W1 | accepted | P01-T03 | [brief](../phases/phase-02-technical-foundations/agent-briefs/P02-T01-bootstrap.md) |
| P02-T02 | W1 | accepted | P02-T01 | [brief](../phases/phase-02-technical-foundations/agent-briefs/P02-T02-tenancy.md) |
| P02-T03 | W1 | in_progress | P02-T02 | [brief](../phases/phase-02-technical-foundations/agent-briefs/P02-T03-configuration.md) |
| P02-T04 | W1 | accepted | P02-T01 | [brief](../phases/phase-02-technical-foundations/agent-briefs/P02-T04-observability-errors.md) |
| P02-T05 | W1 | in_progress | P02-T02, P02-T04 | [brief](../phases/phase-02-technical-foundations/agent-briefs/P02-T05-simulated-channel.md) |
| P03-T01 | W2 | accepted | P02-T01 | [brief](../phases/phase-03-internal-contracts/agent-briefs/P03-T01-common-contracts.md) |
| P03-T02 | W2 | accepted | P03-T01 | [brief](../phases/phase-03-internal-contracts/agent-briefs/P03-T02-appointment-contracts.md) |
| P03-T03 | W2 | in_progress | P02-T02 | [brief](../phases/phase-03-internal-contracts/agent-briefs/P03-T03-tool-registry.md) |
| P03-T04 | W2 | blocked | P03-T02, P03-T03 | [brief](../phases/phase-03-internal-contracts/agent-briefs/P03-T04-fake-appointments.md) |
| P03-T05 | W2 | blocked | P03-T03, P03-T04 | [brief](../phases/phase-03-internal-contracts/agent-briefs/P03-T05-tool-executor.md) |
| P04-T01 | W3 | blocked | P02-T03, P02-T04 | [brief](../phases/phase-04-mvp-vertical-slices/agent-briefs/P04-T01-conversation-runs.md) |
| P04-T02 | W3 | blocked | P03-T03 | [brief](../phases/phase-04-mvp-vertical-slices/agent-briefs/P04-T02-context-skills.md) |
| P04-T03 | W3 | blocked | P02-T03 | [brief](../phases/phase-04-mvp-vertical-slices/agent-briefs/P04-T03-knowledge.md) |
| P04-T04 | W3 | blocked | P04-T01–P04-T03 | [brief](../phases/phase-04-mvp-vertical-slices/agent-briefs/P04-T04-faq-harness.md) |
| P04-T05 | W3 | blocked | P04-T04 | [brief](../phases/phase-04-mvp-vertical-slices/agent-briefs/P04-T05-faq-e2e.md) |
| P04-T06 | W3 | blocked | P02-T03 | [brief](../phases/phase-04-mvp-vertical-slices/agent-briefs/P04-T06-workflow-engine.md) |
| P04-T07 | W3 | blocked | P04-T06, P03-T05 | [brief](../phases/phase-04-mvp-vertical-slices/agent-briefs/P04-T07-appointment-search.md) |
| P04-T08 | W3 | blocked | P04-T07 | [brief](../phases/phase-04-mvp-vertical-slices/agent-briefs/P04-T08-appointment-create.md) |
| P04-T09 | W4 | blocked | P04-T08 | [brief](../phases/phase-04-mvp-vertical-slices/agent-briefs/P04-T09-cancel.md) |
| P04-T10 | W4 | blocked | P04-T08 | [brief](../phases/phase-04-mvp-vertical-slices/agent-briefs/P04-T10-reschedule-confirm.md) |
| P04-T11 | W4 | blocked | P04-T04, P04-T06 | [brief](../phases/phase-04-mvp-vertical-slices/agent-briefs/P04-T11-handoff.md) |
| P04-T12 | W5 | blocked | P04-T08, P04-T10 | [brief](../phases/phase-04-mvp-vertical-slices/agent-briefs/P04-T12-scheduler.md) |
| P04-T13 | W5 | blocked | P04-T05, P04-T09–P04-T12 | [brief](../phases/phase-04-mvp-vertical-slices/agent-briefs/P04-T13-mvp-e2e.md) |
| P05-T01 | W6-intake | blocked | P03-T05, P04-T10, EXT-001 | [brief](../phases/phase-05-real-integration/agent-briefs/P05-T01-api-intake.md) |
| P05-T02 | W6-build | blocked | P05-T01, EXT-003 | [brief](../phases/phase-05-real-integration/agent-briefs/P05-T02-transport-auth.md) |
| P05-T03 | W6-build | blocked | P05-T01, P05-T02 | [brief](../phases/phase-05-real-integration/agent-briefs/P05-T03-appointment-adapter.md) |
| P05-T04 | W6-sandbox | blocked | P05-T03, EXT-002 | [brief](../phases/phase-05-real-integration/agent-briefs/P05-T04-sandbox-rollout.md) |
| P06-T01 | W6 | blocked | P04-T05, P04-T08 | [brief](../phases/phase-06-verification-and-evals/agent-briefs/P06-T01-eval-dataset.md) |
| P06-T02 | W6 | blocked | P06-T01 | [brief](../phases/phase-06-verification-and-evals/agent-briefs/P06-T02-eval-runner.md) |
| P06-T03 | W6 | blocked | P04-T13 | [brief](../phases/phase-06-verification-and-evals/agent-briefs/P06-T03-security-suite.md) |
| P06-T04 | W6 | blocked | P04-T13 | [brief](../phases/phase-06-verification-and-evals/agent-briefs/P06-T04-resilience.md) |
| P06-T05 | W6 | blocked | P06-T02–P06-T04 | [brief](../phases/phase-06-verification-and-evals/agent-briefs/P06-T05-performance-report.md) |
| P07-T01 | W6 | blocked | P04-T13 | [brief](../phases/phase-07-operability-and-observability/agent-briefs/P07-T01-telemetry.md) |
| P07-T02 | W6 | blocked | P04-T13 | [brief](../phases/phase-07-operability-and-observability/agent-briefs/P07-T02-run-query.md) |
| P07-T03 | W6 | blocked | P07-T02 | [brief](../phases/phase-07-operability-and-observability/agent-briefs/P07-T03-admin-view.md) |
| P07-T04 | W6 | blocked | P07-T01–P07-T03 | [brief](../phases/phase-07-operability-and-observability/agent-briefs/P07-T04-runbooks-alerts.md) |
| P08-T01 | W7 | blocked | P04-T13 | [brief](../phases/phase-08-second-tenant-onboarding/agent-briefs/P08-T01-package-validator.md) |
| P08-T02 | W7 | blocked | P08-T01 | [brief](../phases/phase-08-second-tenant-onboarding/agent-briefs/P08-T02-provision-service.md) |
| P08-T03 | W7 | blocked | P08-T02, P06-T05, P07-T04 | [brief](../phases/phase-08-second-tenant-onboarding/agent-briefs/P08-T03-preflight-activation.md) |
| P08-T04 | W7 | blocked | P08-T03, P05-T04 para integración real | [brief](../phases/phase-08-second-tenant-onboarding/agent-briefs/P08-T04-second-tenant.md) |

## Primer paso

P03-T02 accepted (`8ad10f4`, PR #4). En curso: `P02-T03` (Implementador), `P03-T03` (Implementador 2), `P02-T05` (Implementador 3).

## Actualización

Sólo el coordinador edita estados. Cada transición cita commit y evidencia en una nota de revisión o PR. Una tarea bloqueada por `EXT` no se desbloquea por decisión técnica interna.

## Registro de transiciones

| Tarea | Transición | Implementación | Evidencia |
|---|---|---|---|
| P01-T01 | `ready → in_review → accepted` | `e6b5736`, `655dae8`, `371aa73` | [P01-T01](../phases/phase-01-functional-specification/evidence/P01-T01.md) |
| P01-T02 | `blocked → ready` | dependencia P01-T01 aceptada | [P01-T01](../phases/phase-01-functional-specification/evidence/P01-T01.md) |
| P01-T02 | `ready → in_review → accepted` | `154d26a` | [P01-T02](../phases/phase-01-functional-specification/evidence/P01-T02.md) |
| P01-T03 | `blocked → ready` | dependencias P01-T01/P01-T02 aceptadas | [P01-T02](../phases/phase-01-functional-specification/evidence/P01-T02.md) |
| P01-T03 | `ready → in_review → accepted` | `87fc14d` | [P01-T03](../phases/phase-01-functional-specification/evidence/P01-T03.md) |
| P02-T01 | `blocked → ready` | dependencia P01-T03 aceptada | [P01-T03](../phases/phase-01-functional-specification/evidence/P01-T03.md) |
| P02-T01 | `ready → in_progress` | asignada a implementación local | — |
| P02-T01 | `in_progress → in_review` | `bdda0b6` | handoff FastAPI bootstrap; Revisor |
| P02-T01 | `in_review → accepted` | `bdda0b6`, `2afd666` | [P02-T01](../phases/phase-02-technical-foundations/evidence/P02-T01.md) |
| P02-T02 | `blocked → ready` | dependencia P02-T01 aceptada | [P02-T01](../phases/phase-02-technical-foundations/evidence/P02-T01.md) |
| P02-T04 | `blocked → ready` | dependencia P02-T01 aceptada | [P02-T01](../phases/phase-02-technical-foundations/evidence/P02-T01.md) |
| P03-T01 | `blocked → ready` | dependencia P02-T01 aceptada | [P02-T01](../phases/phase-02-technical-foundations/evidence/P02-T01.md) |
| P02-T02 | `ready → in_progress` | asignada a Implementador | — |
| P02-T04 | `ready → in_progress` | asignada a Implementador 2 | — |
| P03-T01 | `ready → in_progress → in_review` | `2620311` | https://github.com/franjimenxz/Project-IA/pull/2 |
| P02-T02 | `in_progress → in_review` | `641e988` | https://github.com/franjimenxz/Project-IA/pull/1 |
| P02-T02 | `in_review → accepted` | `641e988` merged `69196be` | https://github.com/franjimenxz/Project-IA/pull/1 |
| P03-T01 | `in_review → accepted` | `2620311` | https://github.com/franjimenxz/Project-IA/pull/2 |
| P02-T03 | `blocked → ready → in_progress` | dependencia P02-T02 aceptada | asignada a Implementador |
| P03-T02 | `blocked → ready` | dependencia P03-T01 aceptada | — |
| P03-T03 | `blocked → ready` | dependencia P02-T02 aceptada | — |
| P02-T04 | `in_progress → in_review` | `52173b6`, `871a2c2` | https://github.com/franjimenxz/Project-IA/pull/3 |
| P03-T02 | `ready → in_progress` | asignada a Implementador 3 | — |
| P02-T04 | `in_review → accepted` | `871a2c2` merged `7e03d85` | https://github.com/franjimenxz/Project-IA/pull/3 |
| P02-T05 | `blocked → ready` | dependencias P02-T02 y P02-T04 aceptadas | — |
| P03-T03 | `ready → in_progress` | asignada a Implementador 2 | — |
| P03-T02 | `in_progress → in_review` | `6ff733d`, `7260629` | https://github.com/franjimenxz/Project-IA/pull/4 |
| P03-T02 | `in_review → accepted` | `6ff733d` merged `8ad10f4` | https://github.com/franjimenxz/Project-IA/pull/4 |
| P02-T05 | `ready → in_progress` | asignada a Implementador 3 | — |
