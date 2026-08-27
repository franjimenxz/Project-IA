# Operability and Observability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Entregar investigación de runs, señales accionables y runbooks seguros.

**Architecture:** Un query service crea read model sanitizado; FastAPI expone JSON/HTML con RBAC. OpenTelemetry correlaciona todos los boundaries.

**Tech Stack:** Python 3.13, FastAPI, Pydantic v2, SQLAlchemy 2, OpenTelemetry, templates HTML server-side

**Spec:** `docs/phases/phase-07-operability-and-observability/TDD.md`

## Global Constraints

- Read-only: la vista no muta negocio.
- RBAC y tenant scope en query, no sólo UI.
- Sin prompts/payloads/PII completos.
- Labels de métricas acotados.

---

### Task 1: Semantic conventions y propagación

**Brief:** `agent-briefs/P07-T01-telemetry.md`

**Files:** Create observability semantic conventions/propagation tests; modify middleware, outbox, MCP hooks.

- [ ] Write failing E2E assertion that one correlation/trace links inbound, run, job and tool.
- [ ] Run node and capture broken boundary.
- [ ] Implement versioned attribute helpers and context serialization/restoration.
- [ ] Test exporter failure and cardinality guard.
- [ ] Commit `feat: correlate telemetry across async boundaries`.

### Task 2: Run investigation read model

**Brief:** `agent-briefs/P07-T02-run-query.md`

**Files:** Create query models/service/SQL adapter and tests.

- [ ] **Write failing test**

```python
async def test_run_query_rejects_cross_tenant(query, run_b):
    with pytest.raises(RunNotFound):
        await query.get(TENANT_A_CTX, run_b.id)
```

- [ ] Run node; expect missing query.
- [ ] Implement tenant-scoped joins/pagination and redacted summaries.
- [ ] Add complete timeline/error/handoff/job tests.
- [ ] Commit `feat: reconstruct agent run investigations`.

### Task 3: Admin API y vista

**Brief:** `agent-briefs/P07-T03-admin-view.md`

**Files:** Create admin routes/auth dependency/templates/tests.

- [ ] Write failing tests for JSON success, HTML fields, operator B 404 and unauthenticated 401.
- [ ] Implement RBAC dependency and read-only routes/templates.
- [ ] Add HTML escaping, pagination and timezone display tests.
- [ ] Run API/security suites.
- [ ] Commit `feat: expose secure run investigation view`.

### Task 4: Dashboards, alertas y runbooks

**Brief:** `agent-briefs/P07-T04-runbooks-alerts.md`

**Files:** Create observability config, `docs/runbooks/*.md`, validation script/tests.

- [ ] Add failing validation for alert without owner/runbook or runbook without verification.
- [ ] Define dashboards/alerts from TDD and write five critical runbooks.
- [ ] Execute synthetic incident/tabletop and record evidence.
- [ ] Run config/document validators.
- [ ] Commit `docs: add actionable observability runbooks`.

