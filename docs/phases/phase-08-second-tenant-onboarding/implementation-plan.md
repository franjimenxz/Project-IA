# Second Tenant Onboarding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Incorporar y activar un segundo tenant declarativamente sin modificar lógica específica del Core.

**Architecture:** Tenant package validado alimenta un application service idempotente; preflight liga evidence al hash antes de activar.

**Tech Stack:** Python 3.13, Pydantic v2, SQLAlchemy 2, FastAPI/CLI, Pytest

**Spec:** `docs/phases/phase-08-second-tenant-onboarding/TDD.md`

## Global Constraints

- No secret values/PDFs sensibles en Git.
- No branches por tenant en Core.
- Preflight antes de activar.
- Comandos auditados/idempotentes.

---

### Task 1: Tenant package schema y validate CLI

**Brief:** `agent-briefs/P08-T01-package-validator.md`

**Files:** Create onboarding models/loader/CLI, JSON schema and tests.

- [ ] **Write failing test**

```python
def test_package_rejects_secret_value(tmp_path):
    package = write_package(tmp_path, integrations={"token": "plain-secret"})
    report = validate_package(package)
    assert report.valid is False
    assert "secret values are forbidden" in report.errors[0].message
```

- [ ] Run test; expect missing validator.
- [ ] Implement strict package models, cross-file validation and redacted report.
- [ ] Add duplicate channel, skill/tool mismatch and manifest checksum tests.
- [ ] Commit `feat: validate declarative tenant packages`.

### Task 2: Provision y lifecycle service

**Brief:** `agent-briefs/P08-T02-provision-service.md`

**Files:** Create onboarding service/commands/API or CLI adapter and integration tests.

- [ ] Write failing replay test asserting one tenant/config/channel mapping.
- [ ] Implement transactionally `provision`, config draft, integrations references and audit.
- [ ] Implement disable guard for new runs/jobs while preserving audit.
- [ ] Run integration/security tests.
- [ ] Commit `feat: provision tenant lifecycle idempotently`.

### Task 3: Preflight y activación

**Brief:** `agent-briefs/P08-T03-preflight-activation.md`

**Files:** Create preflight checks/report store, activation command and tests.

- [ ] Write failing test: report hash H1 cannot activate changed package H2.
- [ ] Implement checks listed in TDD and immutable report hash.
- [ ] Implement RBAC activation requiring passing report and atomic state/mapping change.
- [ ] Run preflight/e2e A/B tests.
- [ ] Commit `feat: gate tenant activation on preflight evidence`.

### Task 4: Segundo tenant y prueba de arquitectura

**Brief:** `agent-briefs/P08-T04-second-tenant.md`

**Files:** Create synthetic tenant B package/evals, diff checker, onboarding runbook/evidence.

- [ ] Create B with different fields/corpus/tools/MCP fake and run validate/provision.
- [ ] Run preflight and E2E A/B; expect isolation evidence.
- [ ] Run core diff checker from recorded baseline and review changes.
- [ ] Exercise disable/rollback and verify A unaffected.
- [ ] Commit `test: prove second tenant onboarding without core changes`.

