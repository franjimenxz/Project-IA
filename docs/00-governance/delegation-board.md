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
| P02-T03 | W1 | accepted | P02-T02 | [brief](../phases/phase-02-technical-foundations/agent-briefs/P02-T03-configuration.md) |
| P02-T04 | W1 | accepted | P02-T01 | [brief](../phases/phase-02-technical-foundations/agent-briefs/P02-T04-observability-errors.md) |
| P02-T05 | W1 | accepted | P02-T02, P02-T04 | [brief](../phases/phase-02-technical-foundations/agent-briefs/P02-T05-simulated-channel.md) |
| P03-T01 | W2 | accepted | P02-T01 | [brief](../phases/phase-03-internal-contracts/agent-briefs/P03-T01-common-contracts.md) |
| P03-T02 | W2 | accepted | P03-T01 | [brief](../phases/phase-03-internal-contracts/agent-briefs/P03-T02-appointment-contracts.md) |
| P03-T03 | W2 | accepted | P02-T02 | [brief](../phases/phase-03-internal-contracts/agent-briefs/P03-T03-tool-registry.md) |
| P03-T04 | W2 | accepted | P03-T02, P03-T03 | [brief](../phases/phase-03-internal-contracts/agent-briefs/P03-T04-fake-appointments.md) |
| P03-T05 | W2 | accepted | P03-T03, P03-T04 | [brief](../phases/phase-03-internal-contracts/agent-briefs/P03-T05-tool-executor.md) |
| P04-T01 | W3 | accepted | P02-T03, P02-T04 | [brief](../phases/phase-04-mvp-vertical-slices/agent-briefs/P04-T01-conversation-runs.md) |
| P04-T02 | W3 | accepted | P03-T03 | [brief](../phases/phase-04-mvp-vertical-slices/agent-briefs/P04-T02-context-skills.md) |
| P04-T03 | W3 | accepted | P02-T03 | [brief](../phases/phase-04-mvp-vertical-slices/agent-briefs/P04-T03-knowledge.md) |
| P04-T04 | W3 | accepted | P04-T01–P04-T03 | [brief](../phases/phase-04-mvp-vertical-slices/agent-briefs/P04-T04-faq-harness.md) |
| P04-T05 | W3 | accepted | P04-T04 | [brief](../phases/phase-04-mvp-vertical-slices/agent-briefs/P04-T05-faq-e2e.md) |
| P04-T06 | W3 | accepted | P02-T03 | [brief](../phases/phase-04-mvp-vertical-slices/agent-briefs/P04-T06-workflow-engine.md) |
| P04-T07 | W3 | accepted | P04-T06, P03-T05 | [brief](../phases/phase-04-mvp-vertical-slices/agent-briefs/P04-T07-appointment-search.md) |
| P04-T08 | W3 | accepted | P04-T07 | [brief](../phases/phase-04-mvp-vertical-slices/agent-briefs/P04-T08-appointment-create.md) |
| P04-T09 | W4 | accepted | P04-T08 | [brief](../phases/phase-04-mvp-vertical-slices/agent-briefs/P04-T09-cancel.md) |
| P04-T10 | W4 | accepted | P04-T08 | [brief](../phases/phase-04-mvp-vertical-slices/agent-briefs/P04-T10-reschedule-confirm.md) |
| P04-T11 | W4 | accepted | P04-T04, P04-T06 | [brief](../phases/phase-04-mvp-vertical-slices/agent-briefs/P04-T11-handoff.md) |
| P04-T12 | W5 | accepted | P04-T08, P04-T10 | [brief](../phases/phase-04-mvp-vertical-slices/agent-briefs/P04-T12-scheduler.md) |
| P04-T13 | W5 | accepted | P04-T05, P04-T09–P04-T12 | [brief](../phases/phase-04-mvp-vertical-slices/agent-briefs/P04-T13-mvp-e2e.md) |
| P05-T01 | W6-intake | blocked | P03-T05, P04-T10, EXT-001 | [brief](../phases/phase-05-real-integration/agent-briefs/P05-T01-api-intake.md) |
| P05-T02 | W6-build | blocked | P05-T01, EXT-003 | [brief](../phases/phase-05-real-integration/agent-briefs/P05-T02-transport-auth.md) |
| P05-T03 | W6-build | blocked | P05-T01, P05-T02 | [brief](../phases/phase-05-real-integration/agent-briefs/P05-T03-appointment-adapter.md) |
| P05-T04 | W6-sandbox | blocked | P05-T03, EXT-002 | [brief](../phases/phase-05-real-integration/agent-briefs/P05-T04-sandbox-rollout.md) |
| P06-T01 | W6 | accepted | P04-T05, P04-T08 | [brief](../phases/phase-06-verification-and-evals/agent-briefs/P06-T01-eval-dataset.md) |
| P06-T02 | W6 | accepted | P06-T01 | [brief](../phases/phase-06-verification-and-evals/agent-briefs/P06-T02-eval-runner.md) |
| P06-T03 | W6 | accepted | P04-T13 | [brief](../phases/phase-06-verification-and-evals/agent-briefs/P06-T03-security-suite.md) |
| P06-T04 | W6 | accepted | P04-T13 | [brief](../phases/phase-06-verification-and-evals/agent-briefs/P06-T04-resilience.md) |
| P06-T05 | W6 | accepted | P06-T02–P06-T04 | [brief](../phases/phase-06-verification-and-evals/agent-briefs/P06-T05-performance-report.md) |
| P07-T01 | W6 | accepted | P04-T13 | [brief](../phases/phase-07-operability-and-observability/agent-briefs/P07-T01-telemetry.md) |
| P07-T02 | W6 | accepted | P04-T13 | [brief](../phases/phase-07-operability-and-observability/agent-briefs/P07-T02-run-query.md) |
| P07-T03 | W6 | accepted | P07-T02 | [brief](../phases/phase-07-operability-and-observability/agent-briefs/P07-T03-admin-view.md) |
| P07-T04 | W6 | accepted | P07-T01–P07-T03 | [brief](../phases/phase-07-operability-and-observability/agent-briefs/P07-T04-runbooks-alerts.md) |
| P08-T01 | W7 | accepted | P04-T13 | [brief](../phases/phase-08-second-tenant-onboarding/agent-briefs/P08-T01-package-validator.md) |
| P08-T02 | W7 | accepted | P08-T01 | [brief](../phases/phase-08-second-tenant-onboarding/agent-briefs/P08-T02-provision-service.md) |
| P08-T03 | W7 | accepted | P08-T02, P06-T05, P07-T04 | [brief](../phases/phase-08-second-tenant-onboarding/agent-briefs/P08-T03-preflight-activation.md) |
| P08-T04 | W7 | accepted | P08-T03, P05-T04 para integración real | [brief](../phases/phase-08-second-tenant-onboarding/agent-briefs/P08-T04-second-tenant.md) |
| P09-T01 | W8 | accepted | P08-T04 | [brief](../phases/phase-09-mcp-discovery/agent-briefs/P09-T01-architecture-docs.md) |
| P09-T02 | W8 | accepted | P09-T01 | [brief](../phases/phase-09-mcp-discovery/agent-briefs/P09-T02-open-registry.md) |
| P09-T03 | W8 | accepted | P09-T01 | [brief](../phases/phase-09-mcp-discovery/agent-briefs/P09-T03-mcp-client.md) |
| P09-T04 | W8 | accepted | P09-T02, P09-T03 | [brief](../phases/phase-09-mcp-discovery/agent-briefs/P09-T04-generic-executor.md) |
| P10-T01 | W9 | in_review | P09-T04 | [brief](../phases/phase-10-composition-root/agent-briefs/P10-T01-runtime-composition.md) |
| P11-T01 | W10 | in_review | P10-T01 | [brief](../phases/phase-11-agent-loop/agent-briefs/P11-T01-architecture-docs.md) |
| P11-T02 | W10 | blocked | P11-T01 | [brief](../phases/phase-11-agent-loop/agent-briefs/P11-T02-decision-contract.md) |
| P11-T03 | W10 | blocked | P11-T02 | [brief](../phases/phase-11-agent-loop/agent-briefs/P11-T03-harness-loop.md) |
| P11-T04 | W10 | blocked | P11-T03 | [brief](../phases/phase-11-agent-loop/agent-briefs/P11-T04-isolation-observability.md) |

## Primer paso

P07-T01 accepted (PR #32). P07-T02 accepted (PR #40). P07-T03 accepted (PR #52). P07-T04 accepted (PR #55). Fase 7 T01–T04 accepted. P06-T01 accepted (PR #26). P06-T04 accepted (PR #29). P06-T02 accepted (PR #35). P06-T03 accepted (PR #37). P06-T05 accepted (PR #46). Fase 6 T01–T05 accepted. P08-T01 accepted (PR #28). P08-T02 accepted (PR #41). P08-T03 accepted (PR #47). P08-T04 accepted (PR #57). Fase 8 T01–T04 accepted. Residual no bloqueante P07-T02: `audit_event` sin `run_id`; nombres en texto libre quedan con owner de `redaction.py`. Residual P07-T04: catalog validator does not reject `run_id` on alert `signal.labels` (committed files do not use it). Residual P08-T02: `token=` not in `redact()`; service-layer disable trusts TenantAdminContext (enforcement in adapter); lock no longer solely load-bearing. Residual P06-T03: ReDoS quadratic `_KEY` en `redaction.py` (escalado; no FAIL de re-review). Residual P06-T05: EXT-007 SLO; unused spans `channel.receive`/`channel.send`/`tool.execute`; synthetic latencies. Residual P08-T03: preflight ports fail-closed until wired; `create_onboarding_router` montado en `create_app`; el servicio se construye en el composition root y `package_path` queda acotado a `IA_MCP_TENANT_PACKAGES_DIR` (fail-closed). La activación por HTTP sigue inalcanzable porque los preflight ports fallan cerrados. Residual P08-T04: preflight CLI still fail-closed on T03 defaults (secrets/MCP/eval) until real ports; E2E runbook test asserts no exit 2, not a full happy-path provision/activate; Core-gate exemption is only `src/ia_mcp/onboarding/cli.py` (intentional); `create_onboarding_router` ya montado (ver P08-T03). Append-only DB, allowlist prod y SAST CI siguen escalados. P05-T01–T04 siguen `blocked` por EXT. P09-T01 accepted (PR #59). P09-T02 accepted (PR #61). P09-T03 accepted (PR #63). Residual no bloqueante P09-T02: onboarding `enabled_tools ⊆ capabilities` sin test de reject; `TOOL_SKILL_PREFIX` solo mapea `appointments.`; `getattr` `enabled_tools` en appointments skill es defensivo. Residual no bloqueante P09-T03: live e2e with empty `allowed_tools` is a weak assertion; config integration `test_concurrent_publish_allocates_distinct_versions` flakes (pre-existing). P09-T04 accepted (PR #66). Fase 9 T01–T04 accepted. Residual no bloqueante P09-T04: no composition root in `src/` wires `SseMcpClient` into `ToolExecutor` (brief was protocol injection) — owner P10-T01. P08 core-diff `REGISTERED_BASE` resuelto: el guard afirmaba contra el working tree, por lo que vencía en cada fase nueva; ahora fija el rango histórico `dd810e0..11b3de5` (padre real del commit de onboarding; `9bbb790` pertenecía a la rama previa al rebase e incluye cambios legítimos de Core de P07) y conserva el escaneo del árbol vivo. Live e2e empty `allowed_tools` sigue siendo una aserción débil. El supuesto flake de `test_concurrent_publish_allocates_distinct_versions` **no era de test**: `_ensure_tenant` arbitraba `ON CONFLICT` sólo sobre `id` mientras `tenant` es único también en `slug`, de modo que una publicación concurrente fallaba con `UniqueViolation` en vez de ignorarse (medido: 21/400 = 5,25%). Corregido en `src/ia_mcp/configuration/adapters/sqlalchemy.py` (0/400 tras el arreglo); un slug de otro tenant ahora devuelve `ConfigurationError("slug_taken")` en lugar de diferirse a una violación de clave foránea. P10-T01 in_review (`fd6d0da`); two-stage PASS. Residual: AC-P10-003 sin test automatizado durable; `IA_MCP_MCP_ENDPOINTS` es dato de deployment (decisión coordinador); factory `TenantToolExecutors` (el harness no la consume); `channel_integration_ids` foto de startup; `tenant_tools={}`; `create_onboarding_router` montado. P05-T01–T04 siguen `blocked` por EXT.

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
| P03-T03 | `in_progress → in_review` | `3e41f4f` | https://github.com/franjimenxz/Project-IA/pull/5 |
| P03-T03 | `in_review → accepted` | `3e41f4f` merged `f4ec30d` | https://github.com/franjimenxz/Project-IA/pull/5 |
| P03-T04 | `blocked → ready → in_progress` | dependencias P03-T02 y P03-T03 aceptadas | asignada a Implementador 2 |
| P04-T02 | `blocked → ready` | dependencia P03-T03 aceptada | — |
| P02-T03 | `in_progress → in_review` | `062b7f8` | https://github.com/franjimenxz/Project-IA/pull/6 |
| P02-T03 | `in_review → accepted` | `062b7f8` merged `ea2934d` | https://github.com/franjimenxz/Project-IA/pull/6 |
| P04-T01 | `blocked → ready` | dependencias P02-T03 y P02-T04 aceptadas | — |
| P04-T03 | `blocked → ready` | dependencia P02-T03 aceptada | — |
| P04-T06 | `blocked → ready` | dependencia P02-T03 aceptada | — |
| P04-T02 | `ready → in_progress` | asignada a Implementador | — |
| P02-T05 | `in_progress → in_review` | `bdf4915` | https://github.com/franjimenxz/Project-IA/pull/7 |
| P02-T05 | `in_review → accepted` | `bdf4915` merged `ef09ffa` | https://github.com/franjimenxz/Project-IA/pull/7 |
| P04-T01 | `ready → in_progress` | asignada a Implementador 3 | — |
| P03-T04 | `in_progress → in_review` | `f5c32da` | https://github.com/franjimenxz/Project-IA/pull/8 |
| P03-T04 | `in_review → accepted` | `f5c32da` | https://github.com/franjimenxz/Project-IA/pull/8 |
| P03-T05 | `blocked → ready → in_progress` | dependencias P03-T03 y P03-T04 aceptadas | asignada a Implementador 2 |
| P04-T02 | `in_progress → in_review` | `be6eb5f` | https://github.com/franjimenxz/Project-IA/pull/9 |
| P04-T02 | `in_review → accepted` | `be6eb5f` | https://github.com/franjimenxz/Project-IA/pull/9 |
| P04-T01 | `in_progress → in_review` | `7eb5c7c` | https://github.com/franjimenxz/Project-IA/pull/10 |
| P04-T01 | `in_review → accepted` | `7eb5c7c` merged `41f33c5` | https://github.com/franjimenxz/Project-IA/pull/10 |
| P03-T05 | `in_progress → in_review` | `bd30100` | https://github.com/franjimenxz/Project-IA/pull/11 |
| P03-T05 | `in_review → accepted` | `bd30100` merged `02a1b77` | https://github.com/franjimenxz/Project-IA/pull/11 |
| P04-T03 | `ready → in_progress` | asignada a Implementador | worktree `.worktrees/P04-T03-knowledge` |
| P04-T03 | `in_progress → in_review` | `0f3ff05` | https://github.com/franjimenxz/Project-IA/pull/12 |
| P04-T03 | `in_review → accepted` | `0f3ff05` merged `48e7413` | https://github.com/franjimenxz/Project-IA/pull/12 |
| P04-T04 | `blocked → ready → in_progress` | dependencias P04-T01–T03 aceptadas | asignada a Implementador |
| P04-T06 | `ready → in_progress` | asignada a Implementador 2 | worktree `.worktrees/P04-T06-workflow-engine` |
| P04-T04 | `in_progress → in_review` | `0141138` | https://github.com/franjimenxz/Project-IA/pull/13 |
| P04-T04 | `in_review → accepted` | `0141138` merged `df8905e` | https://github.com/franjimenxz/Project-IA/pull/13 |
| P04-T05 | `blocked → ready → in_progress` | dependencia P04-T04 aceptada | asignada a Implementador |
| P04-T06 | `in_progress → in_review` | `9363eb7` | https://github.com/franjimenxz/Project-IA/pull/14 |
| P04-T05 | `in_progress → in_review` | `9435147` | https://github.com/franjimenxz/Project-IA/pull/15 |
| P04-T05 | `in_review → accepted` | `9435147` merged PR #15 | https://github.com/franjimenxz/Project-IA/pull/15 |
| P04-T06 | `in_review → accepted` | `9363eb7` merged `0c157ad` | https://github.com/franjimenxz/Project-IA/pull/14 |
| P04-T07 | `blocked → ready → in_progress` | dependencias P04-T06 y P03-T05 aceptadas | asignada a Implementador 2 |
| P04-T11 | `blocked → ready → in_progress` | dependencias P04-T04 y P04-T06 aceptadas | asignada a Implementador 3 |
| P04-T07 | `in_progress → in_review` | `38a9158` | https://github.com/franjimenxz/Project-IA/pull/17 |
| P04-T11 | `in_progress → in_review` | `ed308d3` | https://github.com/franjimenxz/Project-IA/pull/16 |
| P04-T11 | `in_review → accepted` | `ed308d3` merged `b2e4e0d` | https://github.com/franjimenxz/Project-IA/pull/16 |
| P04-T07 | `in_review → accepted` | `38a9158` merged PR #17 | https://github.com/franjimenxz/Project-IA/pull/17 |
| P04-T08 | `blocked → ready → in_progress` | dependencia P04-T07 aceptada | asignada a Implementador 2 |
| P04-T08 | `in_progress → in_review → accepted` | `9d2e31c` merged PR #18 | https://github.com/franjimenxz/Project-IA/pull/18 |
| P04-T09 | `blocked → ready` | dependencia P04-T08 aceptada | sin asignar |
| P04-T10 | `blocked → ready` | dependencia P04-T08 aceptada | sin asignar |
| P06-T01 | `blocked → ready` | dependencias P04-T05 y P04-T08 aceptadas | sin asignar |
| P04-T09 | `ready → in_progress → in_review` | `dfe1595` | https://github.com/franjimenxz/Project-IA/pull/20 |
| P04-T10 | `ready → in_progress → in_review → accepted` | `64405d7` merged PR #19 | https://github.com/franjimenxz/Project-IA/pull/19 |
| P04-T12 | `blocked → ready → in_progress` | dependencias P04-T08 y P04-T10 aceptadas | asignada a Implementador 2 |
| P04-T09 | `in_review → accepted` | `dfe1595` merged PR #20 | https://github.com/franjimenxz/Project-IA/pull/20 |
| P04-T12 | `in_progress → in_review` | `5870605`, `a8fa8bc` | https://github.com/franjimenxz/Project-IA/pull/21 |
| P04-T12 | `in_review → accepted` | `b7d7625` merged `d79c41d` | https://github.com/franjimenxz/Project-IA/pull/21 |
| P04-T13 | `blocked → ready` | dependencia P04-T12 aceptada | [P04-T12](../phases/phase-04-mvp-vertical-slices/evidence/P04-T12.md) |
| P04-T13 | `ready → in_review` | `4fbe05b`, `3a1091f` | https://github.com/franjimenxz/Project-IA/pull/23 |
| P04-T13 | `in_review → accepted` | `095be85` merged `562d29b` | https://github.com/franjimenxz/Project-IA/pull/23 |
| P06-T03 | `blocked → ready` | dependencia P04-T13 aceptada | [P04-T13](../phases/phase-04-mvp-vertical-slices/evidence/P04-T13.md) |
| P06-T04 | `blocked → ready` | dependencia P04-T13 aceptada | [P04-T13](../phases/phase-04-mvp-vertical-slices/evidence/P04-T13.md) |
| P07-T01 | `blocked → ready` | dependencia P04-T13 aceptada | [P04-T13](../phases/phase-04-mvp-vertical-slices/evidence/P04-T13.md) |
| P07-T02 | `blocked → ready` | dependencia P04-T13 aceptada | [P04-T13](../phases/phase-04-mvp-vertical-slices/evidence/P04-T13.md) |
| P08-T01 | `blocked → ready` | dependencia P04-T13 aceptada | [P04-T13](../phases/phase-04-mvp-vertical-slices/evidence/P04-T13.md) |
| P06-T01 | `ready → in_review` | `9d0b1ba`, `ecda2b9` | https://github.com/franjimenxz/Project-IA/pull/26 |
| P06-T01 | `in_review → accepted` | `31fd3dd` merged `3da861c` | https://github.com/franjimenxz/Project-IA/pull/26 |
| P06-T02 | `blocked → ready` | dependencia P06-T01 aceptada | [P06-T01](../phases/phase-06-verification-and-evals/evidence/P06-T01.md) |
| P08-T01 | `ready → in_review → accepted` | `ed5c4a3` merged `a225261` | https://github.com/franjimenxz/Project-IA/pull/28 |
| P08-T02 | `blocked → ready` | dependencia P08-T01 aceptada | [P08-T01](../phases/phase-08-second-tenant-onboarding/evidence/P08-T01.md) |
| P06-T03 | `ready → in_progress` | asignada a Implementador | worktree `.worktrees/P06-T03-security-suite` |
| P06-T04 | `ready → in_progress` | asignada a Implementador | worktree `.worktrees/P06-T04-resilience` |
| P07-T01 | `ready → in_progress` | asignada a Implementador | worktree `.worktrees/P07-T01-telemetry` |
| P06-T04 | `in_progress → in_review` | `5c47db7`, `06b9a01` | https://github.com/franjimenxz/Project-IA/pull/29 |
| P06-T04 | `in_review → accepted` | `06b9a01` merged `c411002` | https://github.com/franjimenxz/Project-IA/pull/29 |
| P07-T01 | `in_progress → in_review → accepted` | `349a3d5` merged `e2cb470` | https://github.com/franjimenxz/Project-IA/pull/32 |
| P07-T02 | remains `ready` | P07-T01 accepted; conflicto `src/ia_mcp/observability` y `tests/security/test_observability.py` liberado | [P07-T01](../phases/phase-07-operability-and-observability/evidence/P07-T01.md) |
| P06-T02 | `ready → in_progress` | asignada a Implementador | worktree `.worktrees/P06-T02-eval-runner`, branch `implementation/P06-T02-eval-runner` |
| P07-T02 | `ready → in_progress` | asignada a Implementador | worktree `.worktrees/P07-T02-run-query`, branch `implementation/P07-T02-run-query` |
| P08-T02 | `ready → in_progress` | asignada a Implementador | worktree `.worktrees/P08-T02-provision`, branch `implementation/P08-T02-provision` |
| P06-T02 | `in_progress → in_review → accepted` | `589b1bf` merged `771ac06` | https://github.com/franjimenxz/Project-IA/pull/35 |
| P06-T03 | `in_progress → in_review → accepted` | `6719d11` rebased `e1a6dda` merged `9cba6b4` | https://github.com/franjimenxz/Project-IA/pull/37 |
| P06-T05 | `blocked → ready` | dependencias P06-T02, P06-T03 y P06-T04 aceptadas | [P06-T03](../phases/phase-06-verification-and-evals/evidence/P06-T03.md) |
| P06-T05 | `ready → in_progress` | asignada a Implementador | worktree `.worktrees/P06-T05-performance`, branch `implementation/P06-T05-performance` |
| P08-T02 | `in_progress → in_review → accepted` | `d6d9306` rebased `6065834` merged `5f41ccf` | https://github.com/franjimenxz/Project-IA/pull/41 |
| P08-T03 | `blocked → ready` | dependencia P08-T02 aceptada | [P08-T02](../phases/phase-08-second-tenant-onboarding/evidence/P08-T02.md) |
| P07-T02 | `in_progress → in_review → accepted` | `8a8ee33` merged `9f2a387` | https://github.com/franjimenxz/Project-IA/pull/40 |
| P07-T03 | `blocked → ready` | dependencia P07-T02 aceptada | [P07-T02](../phases/phase-07-operability-and-observability/evidence/P07-T02.md) |
| P07-T03 | `ready → in_progress` | asignada a Implementador | worktree `.worktrees/P07-T03-admin-view`, branch `implementation/P07-T03-admin-view` |
| P08-T03 | `ready → in_progress` | asignada a Implementador | worktree `.worktrees/P08-T03-preflight`, branch `implementation/P08-T03-preflight` |
| P06-T05 | `in_progress → in_review → accepted` | `187bfb7` rebased `2900e26` merged `e22d8de` | https://github.com/franjimenxz/Project-IA/pull/46 |
| P08-T03 | `in_progress → in_review → accepted` | `3f21038` / `b085a3f` rebased `402bce9` merged `bc4f3f8` | https://github.com/franjimenxz/Project-IA/pull/47 |
| P08-T04 | `blocked → ready` | dependencia P08-T03 aceptada | [P08-T03](../phases/phase-08-second-tenant-onboarding/evidence/P08-T03.md) |
| P08-T04 | `ready → in_progress` | asignada a Implementador | worktree `.worktrees/P08-T04-second-tenant`, branch `implementation/P08-T04-second-tenant` |
| P07-T03 | `in_progress → in_review → accepted` | `6562c89` / `4b39354` rebased `3837712` merged `a9a0bec` | https://github.com/franjimenxz/Project-IA/pull/52 |
| P07-T04 | `blocked → ready` | dependencia P07-T03 aceptada | [P07-T03](../phases/phase-07-operability-and-observability/evidence/P07-T03.md) |
| P07-T04 | `ready → in_progress` | asignada a Implementador | worktree `.worktrees/P07-T04-runbooks`, branch `implementation/P07-T04-runbooks` |
| P07-T04 | `in_progress → in_review → accepted` | `d65328a` merged `0311794` | https://github.com/franjimenxz/Project-IA/pull/55 |
| P08-T04 | `in_progress → in_review → accepted` | `e7eac5a` rebased `f41d573` merged `11b3de5` | https://github.com/franjimenxz/Project-IA/pull/57 |
| P09-T01 | `in_review → accepted` | `7f487e8` merged `95d3db5` | https://github.com/franjimenxz/Project-IA/pull/59 |
| P09-T02 | `in_progress → in_review → accepted` | `7df5a98` rebased `8dcb96f` merged `6b16c18` | https://github.com/franjimenxz/Project-IA/pull/61 |
| P09-T03 | `in_progress → in_review → accepted` | `db011bd` rebased `83d6df1` merged `d79c3db` | https://github.com/franjimenxz/Project-IA/pull/63 |
| P09-T04 | `blocked → ready` | dependencias P09-T02 y P09-T03 aceptadas | [P09-T03](../phases/phase-09-mcp-discovery/evidence/P09-T03.md) |
| P09-T04 | `ready → in_progress` | asignada a Implementador | worktree `.worktrees/P09-T04-generic-executor`, branch `implementation/P09-T04-generic-executor` |
| P09-T04 | `in_progress → in_review → accepted` | `49cde71` rebased `ac89dfd` merged `51df0c6` | https://github.com/franjimenxz/Project-IA/pull/66 |
| P10-T01 | `blocked → ready` | dependencia P09-T04 aceptada; residual composition root | [P09-T04](../phases/phase-09-mcp-discovery/evidence/P09-T04.md) |
| P10-T01 | `ready → in_progress` | asignada a Implementador | worktree `.worktrees/P10-T01-composition`, branch `implementation/P10-T01-composition` |
| P10-T01 | `in_progress → in_review` | `fd6d0da` | [P10-T01](../phases/phase-10-composition-root/evidence/P10-T01.md) two-stage PASS |
| P11-T01 | `— → in_review` | `310a553` | ADR-006 y Fase 11; validadores documentales verdes. Pendiente de las dos revisiones |
| P11-T02–T04 | `— → blocked` | — | dependen de P11-T01; el contrato `LLMDecision` no se toca antes de aceptarla |
