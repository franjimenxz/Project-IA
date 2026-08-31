# Agent Loop Implementation Plan

**Goal:** Que una decisión del modelo ejecute una tool ya autorizada y su resultado vuelva al modelo en la iteración siguiente, con presupuesto acotado y aislamiento por tenant.

**Architecture:** `handle_message` → compile → `generate` → (`ToolCallProposal` → `ToolExecutor.execute` → observación → `generate`)* → política → `finish`.

**Tech Stack:** Python 3.13, Pydantic v2, Pytest

**Spec:** [`TDD.md`](TDD.md) · [ADR-006](../../01-architecture/adr/ADR-006-conversational-tool-loop.md)

## Restricciones globales

- `AnswerKind` no cambia; toda extensión es aditiva y con default.
- Sin condiciones por slug de institución en Core.
- `TenantContext` en todo boundary; executor por turno, nunca compartido.
- Ninguna mutación desde el loop; el workflow engine no se invoca desde el turno.
- Sin secret values en docs, fixtures, logs, traces ni prompts.

## Task 1: ADR-006 y documentación de fase

**Brief:** [`agent-briefs/P11-T01-architecture-docs.md`](agent-briefs/P11-T01-architecture-docs.md)

- [x] Rojo: el hueco no está escrito en ningún ADR ni fase; revisión documental falla por falta de fuente normativa.
- [x] Verde: ADR-006, fase 11 con TDD, criterios, plan y test plan.
- [x] Commit `docs: define conversational tool loop and its boundary`.

## Task 2: Contrato de decisión y realimentación

**Brief:** [`agent-briefs/P11-T02-decision-contract.md`](agent-briefs/P11-T02-decision-contract.md)

- [ ] Rojo: `LLMPort` no puede expresar una tool call y `LLMRequest` no puede transportar resultados previos.
- [ ] Verde: `ToolCallProposal`, `LLMTurnDecision`, `ToolObservation`, `LLMRequest.tool_results`, `AgentTurnResult.tool_calls` y ajuste de `observe_turn`.
- [ ] Commit `feat: add tool call decision and observation contracts`.

## Task 3: Loop acotado en el harness

**Brief:** [`agent-briefs/P11-T03-harness-loop.md`](agent-briefs/P11-T03-harness-loop.md)

- [ ] Rojo: una `ToolCallProposal` no ejecuta nada y el turno responde como si no hubiera tools.
- [ ] Verde: loop con `max_tool_iterations`, deadline, superficie invocable fail-closed y mapeo de errores tipados.
- [ ] Commit `feat: run bounded tool loop in agent harness`.

## Task 4: Aislamiento, auditoría y trazas

**Brief:** [`agent-briefs/P11-T04-isolation-observability.md`](agent-briefs/P11-T04-isolation-observability.md)

- [ ] Rojo: no existe prueba negativa de que el loop respete el boundary de tenant; `agent.run` y `llm.generate` no se emiten.
- [ ] Verde: suite negativa multi-tenant, spans del turno y `run_id` propagado a `ToolAuditEvent`.
- [ ] Commit `feat: isolate and instrument the conversational tool loop`.

## Wave W10

T02 habilita T03. T04 depende de T03. T01 precede a todas y es la única entregable sin código de producción.
