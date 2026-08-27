# Technical Foundations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Crear un runtime FastAPI reproducible con tenancy, configuración versionada, persistencia y observabilidad segura.

**Architecture:** Monolito modular con dominio independiente de frameworks. PostgreSQL es autoritativo; FastAPI y SQLAlchemy implementan adapters.

**Tech Stack:** Python 3.13, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, PostgreSQL, OpenTelemetry, Pytest, Ruff, mypy

**Spec:** `docs/phases/phase-02-technical-foundations/TDD.md`

## Global Constraints

- TenantContext obligatorio.
- Secrets sólo por referencia.
- SQLite no valida integración SQL.
- El endpoint simulado no acepta tenant del body.

---

### Task 1: Bootstrap reproducible

**Brief:** `agent-briefs/P02-T01-bootstrap.md`

**Files:** Create `pyproject.toml`, `src/ia_mcp/__init__.py`, `src/ia_mcp/api/app.py`, `tests/unit/api/test_app.py`, `compose.yaml`, `.github/workflows/quality.yml`.

- [ ] **Write failing test**

```python
from fastapi.testclient import TestClient
from ia_mcp.api.app import create_app

def test_liveness_does_not_require_dependencies():
    response = TestClient(create_app()).get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "alive"}
```

- [ ] Run `pytest tests/unit/api/test_app.py -v`; expect import failure.
- [ ] Implement `create_app()` and liveness route returning exact payload.
- [ ] Run `ruff check . && mypy src && pytest tests/unit -v`; expect exit 0.
- [ ] Commit `chore: bootstrap FastAPI platform`.

### Task 2: TenantContext y resolución

**Brief:** `agent-briefs/P02-T02-tenancy.md`

**Files:** Create `src/ia_mcp/tenancy/models.py`, `ports.py`, `service.py`, `tests/unit/tenancy/test_service.py`.

- [ ] **Write failing test**

```python
async def test_resolver_ignores_tenant_claim_inside_message():
    repo = FakeChannelRepository({("simulated", "acct-a"): TENANT_A})
    service = TenantService(repo)
    identity = await service.resolve("simulated", "acct-a")
    assert identity.tenant_id == TENANT_A
```

- [ ] Run test; expect missing `TenantService`.
- [ ] Implement frozen `TenantIdentity`, `TenantContext`, repository Protocol and service lookup by `(channel, account_id)`; `TenantContext` is constructed only by Configuration Service in Task 3.
- [ ] Add unknown/disabled account tests and run `pytest tests/unit/tenancy -v`.
- [ ] Commit `feat: resolve tenant from channel identity`.

### Task 3: Configuración versionada y migraciones

**Brief:** `agent-briefs/P02-T03-configuration.md`

**Files:** Create config models/service/SQL adapter, `alembic/versions/0001_foundations.py`, integration tests.

- [ ] **Write failing test**

```python
async def test_publishing_change_creates_new_immutable_version(config_service):
    v1 = await config_service.publish(TENANT_A_ADMIN_CTX, draft(tone="cordial"))
    v2 = await config_service.publish(TENANT_A_ADMIN_CTX, draft(tone="formal"))
    assert (v1.version, v2.version) == (1, 2)
    assert v1.agent.tone == "cordial"
```

- [ ] Run integration node; expect missing schema/service.
- [ ] Implement Pydantic models, content hash, transactionally allocated version, publish/activate, `capture(identity, correlation_id)` and composite constraints; reject raw UUID repository APIs.
- [ ] Run integration tests including cross-tenant and migration up/down.
- [ ] Commit `feat: version tenant configuration`.

### Task 4: Errores, redacción y correlación

**Brief:** `agent-briefs/P02-T04-observability-errors.md`

**Files:** Create `shared/errors.py`, `api/errors.py`, `observability/context.py`, `observability/redaction.py` and tests.

- [ ] **Write failing test**

```python
def test_redactor_removes_bearer_and_email():
    value = redact("Bearer secret-token for patient@example.com")
    assert "secret-token" not in value
    assert "patient@example.com" not in value
    assert value == "Bearer [REDACTED] for [EMAIL]"
```

- [ ] Run unit test; expect missing `redact`.
- [ ] Implement deterministic redactor, DomainError and FastAPI Problem Details handler; add correlation middleware.
- [ ] Run unit/API tests and assert response/log do not contain fixtures.
- [ ] Commit `feat: add safe errors and request correlation`.

### Task 5: Endpoint de canal simulado

**Brief:** `agent-briefs/P02-T05-simulated-channel.md`

**Files:** Create `src/ia_mcp/api/routes/simulated.py`, `channels/models.py`; modify app; add integration test.

- [ ] **Write failing test**

```python
def test_simulated_message_resolves_tenant_from_account(client):
    body = {"external_message_id": "m-1", "external_user_id": "u-1", "text": "tenant_b"}
    headers = signed_simulated_headers(account="acct-a", body=body, now=FROZEN_NOW)
    response = client.post("/v1/simulated/messages", json=body, headers=headers)
    assert response.status_code == 202
    assert response.json()["tenant_slug"] == "tenant-a"
```

- [ ] Run test; expect 404.
- [ ] Implement strict body, test-only HMAC authenticator with freshness/replay checks, dependency-injected resolver and acknowledgment; reject body account/tenant fields with 422 and omit route in production settings.
- [ ] Run API, tenancy and security tests including tampered body/header, stale timestamp and replay.
- [ ] Commit `feat: accept tenant-safe simulated messages`.
