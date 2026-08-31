# Operator HTML Pages Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** HTML lab pages to create, configure, list and try institutions.

**Architecture:** Form writes a valid tenant package, provision/publish persist it, `lab_enable` makes `capture()` work, chat calls `AgentHarness` with that tenant's `TenantContext`.

**Tech Stack:** Python 3.13, FastAPI, pytest

## Global Constraints

- Mount only when `IA_MCP_ENVIRONMENT` is `development` or `test`.
- Package fields only; `extra="forbid"`.
- `TenantContext` on every tenant-scoped boundary.
- No secrets in HTML, logs, traces or fixtures.
- No Core branches on institution slug.
- Do not change `FakeLLM`, production preflight, or WhatsApp.

---

### Task 1: Lab package, lab_enable, HTML

**Files:**
- Create: `src/ia_mcp/onboarding/lab_package.py`
- Create: `src/ia_mcp/api/routes/instituciones.py`
- Create: `src/ia_mcp/api/templates/instituciones.html`
- Create: `src/ia_mcp/api/templates/institucion_chat.html`
- Modify: `src/ia_mcp/onboarding/service.py`
- Modify: `src/ia_mcp/api/app.py`
- Test: `tests/unit/onboarding/test_lab_package.py`, `tests/unit/onboarding/test_lab_enable.py`, `tests/unit/api/test_instituciones_html.py`, `tests/security/test_instituciones_isolation.py`

**Interfaces:**
- Consumes: `validate_package`, `TenantOnboardingService.provision`, `ConfigurationService.capture` / `publish`, `AgentHarness.handle_message`, `get_principal`
- Produces: `write_lab_package(root: Path, form: InstitucionForm) -> Path`, `lab_enable(admin: TenantAdminContext) -> ProvisionedTenant`, `list_tenants(principal: Principal) -> tuple[TenantListItem, ...]`

- [ ] **Step 1: Write the failing tests** for `write_lab_package`, `lab_enable`, HTML GET/POST, isolation, production 404.

- [ ] **Step 2: Run them and confirm they fail** because the symbols and routes are missing.

```text
pytest tests/unit/onboarding/test_lab_package.py tests/unit/onboarding/test_lab_enable.py tests/unit/api/test_instituciones_html.py tests/security/test_instituciones_isolation.py -v
```

Expected: collection or assertion errors naming the missing API.

- [ ] **Step 3: Implement the minimal writer, lab_enable, templates and router.** Follow `docs/phases/phase-13-operator-html-lab/TDD.md` and the approved spec. Resolve `channel_integration_id` from SQL per request.

- [ ] **Step 4: Run the same pytest command** — expected: all pass.

- [ ] **Step 5: Static checks**

```text
ruff check src/ia_mcp/api src/ia_mcp/onboarding tests/unit/api/test_instituciones_html.py tests/unit/onboarding/test_lab_package.py tests/unit/onboarding/test_lab_enable.py tests/security/test_instituciones_isolation.py
mypy src/ia_mcp/api src/ia_mcp/onboarding
```

- [ ] **Step 6: Commit**

```bash
git commit -m "feat: add lab HTML pages for institutions and try-chat"
```
