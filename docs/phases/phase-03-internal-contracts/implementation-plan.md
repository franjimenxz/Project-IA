# Internal Contracts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Crear contratos canónicos y una suite que valide cualquier implementación de appointments.

**Architecture:** Pydantic models viven en `contracts`; Protocols separan capacidades de adapters; tool registry falla cerrado.

**Tech Stack:** Python 3.13, Pydantic v2, Pytest

**Spec:** `docs/phases/phase-03-internal-contracts/TDD.md`

## Global Constraints

- `extra="forbid"` en inputs externos.
- Timezones obligatorias.
- Tenant/secrets no expuestos al LLM.
- Mutaciones requieren idempotency key fuera del payload del modelo.

---

### Task 1: Primitivas de contrato

**Brief:** `agent-briefs/P03-T01-common-contracts.md`

**Files:** Create `src/ia_mcp/contracts/common.py`, `errors.py`, `tests/unit/contracts/test_common.py`.

- [ ] Write failing tests for empty `NonEmptyStr` and invalid ToolResult value/error combinations.
- [ ] Run `pytest tests/unit/contracts/test_common.py -v`; expect import failure.
- [ ] Implement constrained alias, ToolErrorCode, ToolError and generic ToolResult with model validator.
- [ ] Run unit tests, Ruff and mypy; expect exit 0.
- [ ] Commit `feat: define canonical tool results`.

### Task 2: Appointment schemas

**Brief:** `agent-briefs/P03-T02-appointment-contracts.md`

**Files:** Create `src/ia_mcp/contracts/appointments.py`, unit tests and JSON schema snapshots.

- [ ] **Write failing test**

```python
def test_search_rejects_reversed_dates():
    with pytest.raises(ValidationError):
        AppointmentSearchRequest(
            specialty="cardiologia",
            date_from=date(2026, 9, 5),
            date_to=date(2026, 9, 1),
        )
```

- [ ] Run the node; expect missing class.
- [ ] Implement all six request types, AppointmentSlot, PatientRef, Appointment and validators from TDD.
- [ ] Run `pytest tests/unit/contracts/test_appointments.py -v && mypy src/ia_mcp/contracts`.
- [ ] Commit `feat: define appointment contracts`.

### Task 3: Tool registry

**Brief:** `agent-briefs/P03-T03-tool-registry.md`

**Files:** Create `src/ia_mcp/mcp/registry.py`, `tests/unit/mcp/test_registry.py`.

- [ ] **Write failing test**

```python
def test_available_tools_are_three_way_intersection():
    assert registry.available(
        server={"appointments.search", "appointments.create"},
        tenant={"appointments.search"},
        skill={"appointments.search", "appointments.cancel"},
    ) == frozenset({"appointments.search"})
```

- [ ] Run node; expect missing registry.
- [ ] Implement typed ToolName catalog, intersection and `authorize` raising ForbiddenTool.
- [ ] Add tenant A/B and unknown tool tests; run suite and types.
- [ ] Commit `feat: authorize MCP tools by capability`.

### Task 4: Appointment capability y fake

**Brief:** `agent-briefs/P03-T04-fake-appointments.md`

**Files:** Create `mcp/capabilities/appointments.py`, `mcp/fakes/appointments.py`, `tests/contract/appointments/test_capability.py`.

- [ ] **Write failing contract test**

```python
async def test_create_is_idempotent(appointment_capability, request):
    first = await appointment_capability.create(request, idempotency_key="k-1")
    second = await appointment_capability.create(request, idempotency_key="k-1")
    assert first == second
    assert first.ok is True
```

- [ ] Run contract suite; expect missing fixture/Protocol.
- [ ] Define Protocol and fake state keyed by tenant plus idempotency key; implement all six tools and fault plan.
- [ ] Run `pytest -m contract tests/contract/appointments -v` and tenant-crossing tests.
- [ ] Commit `test: provide contract-compliant appointment fake`.

