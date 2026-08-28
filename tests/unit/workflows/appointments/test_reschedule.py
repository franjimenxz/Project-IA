from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from pydantic import SecretStr

from ia_mcp.contracts.appointments import (
    AppointmentCreateRequest,
    AppointmentGetRequest,
    AppointmentSearchRequest,
    AppointmentSlot,
    AppointmentStatus,
    PatientRef,
)
from ia_mcp.mcp.executor import ToolCall, ToolExecutor
from ia_mcp.mcp.fakes.appointments import FakeAppointmentCapability, FaultPlan
from ia_mcp.tenancy.models import TenantContext
from ia_mcp.workflows.appointments.reschedule import RescheduleAppointmentDefinition
from ia_mcp.workflows.engine import WorkflowEngine
from tests.unit.workflows.fakes import InMemoryWorkflowRepository

TENANT_A = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
TENANT_B = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
TENANT_A_CTX = TenantContext(
    tenant_id=TENANT_A,
    tenant_slug="tenant-a",
    config_version=1,
    correlation_id=UUID("33333333-3333-3333-3333-333333333333"),
)
TENANT_B_CTX = TenantContext(
    tenant_id=TENANT_B,
    tenant_slug="tenant-b",
    config_version=1,
    correlation_id=UUID("44444444-4444-4444-4444-444444444444"),
)

CLOCK = datetime(2026, 9, 1, 12, tzinfo=UTC)
PATIENT = PatientRef(name="Ada Lovelace", email="ada@example.com")
ALL_TOOLS = frozenset(
    {
        "appointments.search",
        "appointments.get",
        "appointments.create",
        "appointments.cancel",
        "appointments.reschedule",
        "appointments.confirm",
    }
)
RESCHEDULE_TOOLS = frozenset(
    {"appointments.get", "appointments.search", "appointments.reschedule"}
)


def _slot(
    slot_id: str,
    hour: int,
    *,
    token: str = "tok-a-secret",
) -> AppointmentSlot:
    return AppointmentSlot(
        slot_id=slot_id,
        starts_at=datetime(2026, 9, 1, hour, 0, tzinfo=UTC),
        ends_at=datetime(2026, 9, 1, hour, 30, tzinfo=UTC),
        specialty="cardiologia",
        practitioner="Dr. Ada",
        location="sede-centro",
        booking_token=SecretStr(token),
    )


class CountingCapability(FakeAppointmentCapability):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.operations: list[str] = []
        self.last_request: AppointmentSearchRequest | None = None

    async def search(self, tenant: TenantContext, request: AppointmentSearchRequest):
        self.operations.append("search")
        self.last_request = request
        return await super().search(tenant, request)

    async def get(self, tenant: TenantContext, request: Any):
        self.operations.append("get")
        return await super().get(tenant, request)

    async def create(self, tenant: TenantContext, request: Any, idempotency_key: str):
        self.operations.append("create")
        return await super().create(tenant, request, idempotency_key)

    async def cancel(self, tenant: TenantContext, request: Any, idempotency_key: str):
        self.operations.append("cancel")
        return await super().cancel(tenant, request, idempotency_key)

    async def reschedule(
        self, tenant: TenantContext, request: Any, idempotency_key: str
    ):
        self.operations.append("reschedule")
        return await super().reschedule(tenant, request, idempotency_key)

    async def confirm(self, tenant: TenantContext, request: Any, idempotency_key: str):
        self.operations.append("confirm")
        return await super().confirm(tenant, request, idempotency_key)


class ExecuteSpy:
    def __init__(self, inner: ToolExecutor) -> None:
        self.inner = inner
        self.calls: list[ToolCall] = []

    async def execute(
        self, tenant: TenantContext, run_id: UUID, call: ToolCall
    ) -> Any:
        self.calls.append(call)
        return await self.inner.execute(tenant, run_id, call)


def _capability(
    *,
    fault: FaultPlan | None = None,
    extra_b: bool = False,
) -> CountingCapability:
    slots: dict[UUID, tuple[AppointmentSlot, ...]] = {
        TENANT_A: (
            _slot("slot-a-1", 13, token="tok-a-secret"),
            _slot("slot-a-2", 14, token="tok-a2-secret"),
        )
    }
    if extra_b:
        slots[TENANT_B] = (_slot("slot-b-1", 13, token="tok-b-secret"),)
    return CountingCapability(
        clock=lambda: CLOCK,
        fault_plan=fault,
        initial_slots=slots,
    )


def _executor(
    capability: FakeAppointmentCapability,
    *,
    skill_tools: frozenset[str] = RESCHEDULE_TOOLS,
) -> ToolExecutor:
    return ToolExecutor(
        server=ALL_TOOLS,
        tenant=ALL_TOOLS,
        skill=skill_tools,
        capability=capability,
    )


def _engine() -> tuple[
    WorkflowEngine, InMemoryWorkflowRepository, RescheduleAppointmentDefinition
]:
    repository = InMemoryWorkflowRepository()
    definition = RescheduleAppointmentDefinition()
    return WorkflowEngine(repository, definition), repository, definition


def _assert_safe_text(value: object) -> str:
    assert isinstance(value, str)
    assert value
    lowered = value.lower()
    assert "traceback" not in lowered
    assert "tok-a-secret" not in lowered
    assert "tok-a2-secret" not in lowered
    assert str(TENANT_A) not in value
    assert str(TENANT_B) not in value
    return value


def _assert_no_secrets(payload: object) -> None:
    if isinstance(payload, Mapping):
        for key, item in payload.items():
            lowered = str(key).lower()
            assert lowered != "booking_token"
            assert lowered != "token"
            assert "token" not in lowered
            _assert_no_secrets(item)
        return
    if isinstance(payload, list):
        for item in payload:
            _assert_no_secrets(item)
        return
    text = str(payload)
    assert "tok-a-secret" not in text
    assert "tok-a2-secret" not in text
    assert "booking_token" not in text


async def _seed(
    capability: CountingCapability,
    tenant: TenantContext,
    slot_id: str,
    key: str,
) -> str:
    result = await capability.create(
        tenant,
        AppointmentCreateRequest(slot_id=slot_id, patient=PATIENT),
        idempotency_key=key,
    )
    assert result.ok
    assert result.value is not None
    return result.value.appointment_id


async def _load_search_select(
    engine: WorkflowEngine,
    definition: RescheduleAppointmentDefinition,
    executor: ToolExecutor,
    tenant: TenantContext,
    appointment_id: str,
    *,
    slot_id: str = "slot-a-2",
) -> UUID:
    started = await definition.start(
        engine, tenant, command_id="start-1", appointment_id=appointment_id
    )
    await definition.load_appointment(
        engine,
        executor,
        tenant,
        started.workflow_id,
        command_id="load-1",
        run_id=uuid4(),
    )
    searched = await definition.search_slots(
        engine,
        executor,
        tenant,
        started.workflow_id,
        command_id="search-1",
        run_id=uuid4(),
    )
    assert searched.state == "collecting"
    assert searched.data["phase"] == "awaiting_slot_selection"
    _assert_no_secrets(searched.data)
    selected = await definition.select_slot(
        engine,
        tenant,
        started.workflow_id,
        command_id="select-1",
        slot_id=slot_id,
    )
    assert selected.data["selected_slot"] == slot_id
    assert "selected_slot_id" not in selected.data
    _assert_no_secrets(selected.data)
    return started.workflow_id


@pytest.mark.anyio
async def test_start_persists_reschedule_appointment_collecting() -> None:
    engine, repository, definition = _engine()
    started = await definition.start(
        engine, TENANT_A_CTX, command_id="start-1", appointment_id="appt-1"
    )
    assert started.type == "reschedule_appointment"
    assert started.state == "collecting"
    assert started.data["phase"] == "collecting"
    assert started.data["appointment_id"] == "appt-1"
    loaded = await repository.get(TENANT_A_CTX, started.workflow_id)
    assert loaded is not None
    assert loaded.type == "reschedule_appointment"
    assert loaded.state == "collecting"


def test_stay_collecting_events() -> None:
    definition = RescheduleAppointmentDefinition()
    for event in (
        "load_appointment",
        "search_slots",
        "present_slots",
        "select_slot",
    ):
        assert definition.transition("collecting", event) == "collecting"
    assert definition.transition("collecting", "submit") == "awaiting_confirmation"
    assert (
        definition.transition("awaiting_confirmation", "confirm") == "executing"
    )
    assert definition.transition("executing", "succeed") == "completed"
    assert definition.transition("executing", "review") == "manual_review_required"


@pytest.mark.anyio
async def test_present_and_revalidate_success_reschedules() -> None:
    engine, repository, definition = _engine()
    capability = _capability()
    spy = ExecuteSpy(_executor(capability))
    original_id = await _seed(capability, TENANT_A_CTX, "slot-a-1", "seed-1")
    creates_before = capability.operations.count("create")
    workflow_id = await _load_search_select(
        engine, definition, spy, TENANT_A_CTX, original_id
    )
    presented = definition.present_slots(
        (_slot("slot-a-1", 13), _slot("slot-a-2", 14, token="tok-a2-secret"))
    )
    blob = repr(presented)
    assert "booking_token" not in blob
    assert "tok-a-secret" not in blob
    request = capability.last_request
    assert request is not None
    assert request.specialty == "cardiologia"
    result = await definition.confirm_reschedule(
        engine,
        spy,
        TENANT_A_CTX,
        workflow_id,
        command_id="confirm-1",
        run_id=uuid4(),
    )
    assert result.state == "completed"
    assert result.data["appointment_id"] == original_id
    assert result.data["status"] == AppointmentStatus.RESCHEDULED
    assert capability.operations.count("reschedule") == 1
    assert capability.operations.count("create") == creates_before
    assert "cancel" not in capability.operations
    names = [call.name for call in spy.calls]
    assert "appointments.cancel" not in names
    assert "appointments.create" not in names
    assert "appointments.reschedule" in names
    reschedule_calls = [
        call for call in spy.calls if call.name == "appointments.reschedule"
    ]
    assert len(reschedule_calls) == 1
    assert reschedule_calls[0].idempotency_key == (
        f"{workflow_id}:appointments.reschedule"
    )
    _assert_no_secrets(result.data)
    loaded = await repository.get(TENANT_A_CTX, workflow_id)
    assert loaded is not None
    _assert_no_secrets(dict(loaded.data))
    got = await capability.get(
        TENANT_A_CTX, AppointmentGetRequest(appointment_id=original_id)
    )
    assert got.ok
    assert got.value is not None
    assert got.value.status is AppointmentStatus.RESCHEDULED


@pytest.mark.anyio
async def test_lost_slot_keeps_original_and_skips_reschedule() -> None:
    engine, _repository, definition = _engine()
    capability = _capability()
    executor = _executor(capability)
    original_id = await _seed(capability, TENANT_A_CTX, "slot-a-1", "seed-1")
    workflow_id = await _load_search_select(
        engine, definition, executor, TENANT_A_CTX, original_id
    )
    await _seed(capability, TENANT_A_CTX, "slot-a-2", "occupy-a-2")
    result = await definition.confirm_reschedule(
        engine,
        executor,
        TENANT_A_CTX,
        workflow_id,
        command_id="confirm-1",
        run_id=uuid4(),
    )
    assert result.state == "collecting"
    assert result.data.get("phase") == "awaiting_slot_selection"
    assert capability.operations.count("reschedule") == 0
    assert "cancel" not in capability.operations
    _assert_no_secrets(result.data)
    got = await capability.get(
        TENANT_A_CTX, AppointmentGetRequest(appointment_id=original_id)
    )
    assert got.ok
    assert got.value is not None
    assert got.value.status is AppointmentStatus.SCHEDULED
    assert got.value.starts_at == datetime(2026, 9, 1, 13, 0, tzinfo=UTC)


@pytest.mark.anyio
async def test_reschedule_timeout_requires_manual_review() -> None:
    engine, _repository, definition = _engine()
    capability = _capability(
        fault=FaultPlan(fault="timeout", operations=frozenset({"reschedule"}))
    )
    executor = _executor(capability)
    original_id = await _seed(capability, TENANT_A_CTX, "slot-a-1", "seed-1")
    workflow_id = await _load_search_select(
        engine, definition, executor, TENANT_A_CTX, original_id
    )
    result = await definition.confirm_reschedule(
        engine,
        executor,
        TENANT_A_CTX,
        workflow_id,
        command_id="confirm-1",
        run_id=uuid4(),
    )
    assert result.state == "manual_review_required"
    assert result.state != "completed"
    _assert_safe_text(result.data.get("error") or result.error or "")
    _assert_no_secrets(result.data)


@pytest.mark.anyio
async def test_reschedule_malformed_requires_manual_review() -> None:
    engine, _repository, definition = _engine()
    capability = _capability(
        fault=FaultPlan(fault="malformed", operations=frozenset({"reschedule"}))
    )
    executor = _executor(capability)
    original_id = await _seed(capability, TENANT_A_CTX, "slot-a-1", "seed-1")
    workflow_id = await _load_search_select(
        engine, definition, executor, TENANT_A_CTX, original_id
    )
    result = await definition.confirm_reschedule(
        engine,
        executor,
        TENANT_A_CTX,
        workflow_id,
        command_id="confirm-1",
        run_id=uuid4(),
    )
    assert result.state == "manual_review_required"
    assert result.state != "completed"
    _assert_no_secrets(result.data)


@pytest.mark.anyio
async def test_reschedule_replay_mutates_once() -> None:
    engine, _repository, definition = _engine()
    capability = _capability()
    executor = _executor(capability)
    original_id = await _seed(capability, TENANT_A_CTX, "slot-a-1", "seed-1")
    workflow_id = await _load_search_select(
        engine, definition, executor, TENANT_A_CTX, original_id
    )
    run_id = uuid4()
    first = await definition.confirm_reschedule(
        engine,
        executor,
        TENANT_A_CTX,
        workflow_id,
        command_id="confirm-1",
        run_id=run_id,
    )
    replay = await definition.confirm_reschedule(
        engine,
        executor,
        TENANT_A_CTX,
        workflow_id,
        command_id="confirm-1",
        run_id=run_id,
    )
    assert first.state == "completed"
    assert replay.state == "completed"
    assert capability.operations.count("reschedule") == 1
    _assert_no_secrets(first.data)
    _assert_no_secrets(replay.data)


@pytest.mark.anyio
async def test_tenant_a_cannot_reschedule_tenant_b_appointment() -> None:
    engine, _repository, definition = _engine()
    capability = _capability(extra_b=True)
    executor = _executor(capability)
    foreign_id = await _seed(capability, TENANT_B_CTX, "slot-b-1", "seed-b")
    started = await definition.start(
        engine, TENANT_A_CTX, command_id="start-1", appointment_id=foreign_id
    )
    loaded = await definition.load_appointment(
        engine,
        executor,
        TENANT_A_CTX,
        started.workflow_id,
        command_id="load-1",
        run_id=uuid4(),
    )
    error = _assert_safe_text(loaded.data.get("error") or loaded.error or "")
    assert foreign_id not in error
    assert loaded.state != "completed"
    result = await definition.confirm_reschedule(
        engine,
        executor,
        TENANT_A_CTX,
        started.workflow_id,
        command_id="confirm-1",
        run_id=uuid4(),
    )
    assert capability.operations.count("reschedule") == 0
    assert "cancel" not in capability.operations
    assert foreign_id not in str(result.data.get("error") or result.error or "")
    got = await capability.get(
        TENANT_B_CTX, AppointmentGetRequest(appointment_id=foreign_id)
    )
    assert got.ok
    assert got.value is not None
    assert got.value.status is AppointmentStatus.SCHEDULED
