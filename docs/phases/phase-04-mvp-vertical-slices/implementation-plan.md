# MVP Vertical Slices Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Entregar FAQ, ciclo de turnos, handoff y recordatorios end-to-end para dos tenants usando dependencias simuladas contractuales.

**Architecture:** Agent Harness coordina skills; RAG responde información y Workflow Engine controla mutaciones. PostgreSQL persiste estado/outbox y todos los adapters son puertos reemplazables.

**Tech Stack:** Python 3.13, FastAPI, Pydantic v2, SQLAlchemy 2, PostgreSQL/pgvector, Redis, Pytest, OpenTelemetry

**Spec:** `docs/phases/phase-04-mvp-vertical-slices/TDD.md`

## Global Constraints

- Dos tenants en cada integration/E2E.
- Fake LLM determinístico en tests funcionales.
- Mutaciones idempotentes y auditadas.
- No secrets/prompts completos en storage/telemetry.

---

### Task 1: Conversation y AgentRun

**Brief:** `agent-briefs/P04-T01-conversation-runs.md`

**Files:** Create conversation models/repos/migration and `tests/integration/mvp/test_conversations.py`.

- [ ] Write failing integration test: duplicate external message returns same Message and only one AgentRun trigger.
- [ ] Run node; expect missing repository/schema.
- [ ] Implement tenant-scoped Conversation, Message, SessionState, AgentRun and dedupe transaction.
- [ ] Add B-context access negative test; run integration/security nodes.
- [ ] Commit `feat: persist tenant-scoped conversations and runs`.

### Task 2: Skill Registry y Context Compiler

**Brief:** `agent-briefs/P04-T02-context-skills.md`

**Files:** Create agent/skills/context modules and unit tests.

- [ ] **Write failing test**

```python
async def test_compiler_excludes_disabled_tools(compiler, tenant_a):
    context = await compiler.compile(tenant_a, request(skill="faq"))
    assert context.tool_schemas == ()
    assert "credentials_reference" not in context.model_dump_json()
```

- [ ] Run node; expect missing compiler.
- [ ] Implement registry authorization, ContextRequest/CompiledContext and token-budgeted assembly.
- [ ] Run unit + prompt injection security tests.
- [ ] Commit `feat: compile minimal tenant context`.

### Task 3: Knowledge ingestion y retrieval

**Brief:** `agent-briefs/P04-T03-knowledge.md`

**Files:** Create knowledge models/ports/service/SQL adapter/migration and tests.

- [ ] Write failing test that search under A returns only A canary hits after publishing A/B documents.
- [ ] Run integration node; expect missing KnowledgeService.
- [ ] Implement checksum, version, parse/chunk ports, publish transaction and pgvector query with tenant/status filters and post-check.
- [ ] Run integration + isolation tests.
- [ ] Commit `feat: isolate tenant knowledge ingestion and search`.

### Task 4: FAQ Skill y Agent Harness

**Brief:** `agent-briefs/P04-T04-faq-harness.md`

**Files:** Create agent runtime/ports, faq skill/policy and unit tests.

- [ ] **Write failing test**

```python
async def test_faq_returns_insufficient_without_supported_hits(harness):
    result = await harness.handle_message(TENANT_A_CTX, message("unknown"))
    assert result.kind == "insufficient"
    assert result.source_ids == ()
```

- [ ] Run node; expect missing harness.
- [ ] Implement run lifecycle, fake LLM port, FAQ AnswerPolicy and sourced response validation.
- [ ] Run unit/eval-fixture tests including injected document instructions.
- [ ] Commit `feat: answer tenant FAQs with grounded evidence`.

### Task 5: FAQ end-to-end

**Brief:** `agent-briefs/P04-T05-faq-e2e.md`

**Files:** Modify simulated route/outbox; create `tests/e2e/test_faq.py`.

- [ ] Write E2E test posting A/B questions and asserting distinct answers/source IDs.
- [ ] Run node; expect acknowledgment instead of completed response.
- [ ] Wire conversation→harness→knowledge→outbox→fake channel while preserving correlation.
- [ ] Run full Slice 4.1 suites.
- [ ] Commit `feat: complete multi-tenant FAQ slice`.

### Task 6: Workflow Engine

**Brief:** `agent-briefs/P04-T06-workflow-engine.md`

**Files:** Create workflow domain/repository/migration/engine and tests.

- [ ] **Write failing test**

```python
async def test_duplicate_command_returns_recorded_transition(engine):
    first = await engine.advance(TENANT_A_CTX, command(id="cmd-1"))
    second = await engine.advance(TENANT_A_CTX, command(id="cmd-1"))
    assert second == first
    assert await transitions.count(command_id="cmd-1") == 1
```

- [ ] Run node; expect missing engine.
- [ ] Implement persisted state, transition table, CAS, command dedupe and outbox.
- [ ] Add concurrent advance/crash recovery tests.
- [ ] Commit `feat: add durable idempotent workflow engine`.

### Task 7: Recolección y búsqueda de turnos

**Brief:** `agent-briefs/P04-T07-appointment-search.md`

**Files:** Create appointments workflow/skill and tests.

- [ ] Write table-driven failing tests for required fields varying between tenants A/B.
- [ ] Run tests; expect missing workflow definition.
- [ ] Implement collecting/searching/awaiting selection transitions and call fake `appointments.search` through authorized executor.
- [ ] Run unit, contract and A/B integration tests.
- [ ] Commit `feat: collect appointment fields and search slots`.

### Task 8: Creación de turno

**Brief:** `agent-briefs/P04-T08-appointment-create.md`

**Files:** Modify appointment workflow; create tool executor/audit and E2E tests.

- [ ] Write failing E2E replay test: selected slot + two confirm messages produce one appointment/tool mutation.
- [ ] Run node; expect workflow stops before create.
- [ ] Implement confirmation, revalidation, create idempotency, ToolExecution and uncertain-state handling.
- [ ] Run Slice 4.2 E2E/resilience suites.
- [ ] Commit `feat: create appointments through durable workflow`.

### Task 9: Cancelación

**Brief:** `agent-briefs/P04-T09-cancel.md`

**Files:** Create cancel workflow/tests.

- [ ] Write failing tests for confirmation, already-cancelled replay and tenant B ID under A.
- [ ] Run nodes; expect missing workflow.
- [ ] Implement get/validate/confirm/cancel transitions using canonical tools.
- [ ] Run lifecycle and security tests.
- [ ] Commit `feat: cancel appointments idempotently`.

### Task 10: Reprogramación y confirmación

**Brief:** `agent-briefs/P04-T10-reschedule-confirm.md`

**Files:** Create reschedule/confirm workflows and tests.

- [ ] Write failing transition tests for slot lost, successful reschedule, already confirmed and uncertain state.
- [ ] Run nodes; expect missing workflows.
- [ ] Implement search/select/revalidate/reschedule and confirm state machines without cancel+create fallback.
- [ ] Run Slice 4.3 E2E/resilience suites.
- [ ] Commit `feat: reschedule and confirm appointments safely`.

### Task 11: Human handoff

**Brief:** `agent-briefs/P04-T11-handoff.md`

**Files:** Create handoff models/service/fake adapter/migration and tests.

- [ ] Write failing transaction test asserting handoff + `human_owned` occur together and replay returns same case.
- [ ] Run node; expect missing service.
- [ ] Implement typed triggers, structured summary, outbox delivery and Harness mutation guard.
- [ ] Run E2E, provider-down and cross-tenant tests.
- [ ] Commit `feat: transfer conversations to human operators`.

### Task 12: Scheduler y recordatorios

**Brief:** `agent-briefs/P04-T12-scheduler.md`

**Files:** Create scheduling models/service/worker/migration and tests.

- [ ] Write failing clock test for appointment at 2026-09-03T12:00-03:00 scheduling at 2026-09-01T12:00-03:00.
- [ ] Run node; expect missing scheduler.
- [ ] Implement persistent jobs, unique business key, claim lease, eligibility recheck, outbox and confirmation ingress.
- [ ] Run clock/replay/restart/cross-tenant tests.
- [ ] Commit `feat: schedule idempotent appointment reminders`.

### Task 13: MVP integrated suite

**Brief:** `agent-briefs/P04-T13-mvp-e2e.md`

**Files:** Create `tests/e2e/test_mvp_journeys.py`, `tests/resilience/test_mvp_failures.py`, fixtures.

- [ ] Add failing journeys for FAQ A/B, create→reschedule→reminder→confirm and handoff after timeout.
- [ ] Run suites and record first failing boundary.
- [ ] Fix only wiring/configuration defects within existing contracts; escalate contract changes.
- [ ] Run all Phase 4 commands plus Ruff/types.
- [ ] Commit `test: verify complete multi-tenant MVP journeys`.

