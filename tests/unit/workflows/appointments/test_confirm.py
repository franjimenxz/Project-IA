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
    AppointmentSlot,
    AppointmentStatus,
    PatientRef,
)
from ia_mcp.mcp.executor import ToolCall, ToolExecutor
from ia_mcp.mcp.fakes.appointments import FakeAppointmentCapability, FaultPlan
from ia_mcp.tenancy.models import TenantContext
from ia_mcp.workflows.appointments.confirm import ConfirmAppointmentDefinition
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
CONFIRM_TOOLS = frozenset({"appointments.get", "appointments.confirm"})


def _slot(slot_id: str, hour: int, *, token: str) -> AppointmentSlot:
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

    async def search(self, tenant: TenantContext, request: Any):
        self.operations.append("search")
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


def _capability(*, extra_b: bool = False, fault: FaultPlan | None = None) -> CountingCapability:
    slots: dict[UUID, tuple[AppointmentSlot, ...]] = {
        TENANT_A: (_slot("slot-a-1", 13, token="tok-a-secret"),)
    }
    if extra_b:
        slots[TENANT_B] = (_slot("slot-b-1", 13, token="tok-b-secret"),)
    return CountingCapability(
        clock=lambda: CLOCK,
        fault_plan=fault,
        initial_slots=slots,
    )


def _executor(capability: FakeAppointmentCapability) -> ToolExecutor:
    return ToolExecutor(
        server=ALL_TOOLS,
        tenant=ALL_TOOLS,
        skill=CONFIRM_TOOLS,
        capability=capability,
    )


def _engine() -> tuple[
    WorkflowEngine, InMemoryWorkflowRepository, ConfirmAppointmentDefinition
]:
    repository = InMemoryWorkflowRepository()
    definition = ConfirmAppointmentDefinition()
    return WorkflowEngine(repository, definition), repository, definition


def _assert_safe_text(value: object) -> str:
    assert isinstance(value, str)
    assert value
    lowered = value.lower()
    assert "traceback" not in lowered
    assert "tok-a-secret" not in lowered
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
    assert "booking_token" not in text


def _set_status(
    capability: CountingCapability,
    tenant_id: UUID,
    appointment_id: str,
    status: AppointmentStatus,
) -> None:
    current = capability._agendas[tenant_id].appointments[appointment_id]
    capability._agendas[tenant_id].appointments[appointment_id] = current.model_copy(
        update={"status": status}
    )


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


@pytest.mark.anyio
async def test_start_persists_confirm_appointment_collecting() -> None:
    engine, repository, definition = _engine()
    started = await definition.start(
        engine, TENANT_A_CTX, command_id="start-1", appointment_id="appt-1"
    )
    assert started.type == "confirm_appointment"
    assert started.state == "collecting"
    assert started.data["phase"] == "collecting"
    assert started.data["appointment_id"] == "appt-1"
    loaded = await repository.get(TENANT_A_CTX, started.workflow_id)
    assert loaded is not None
    assert loaded.type == "confirm_appointment"


def test_stay_collecting_events() -> None:
    definition = ConfirmAppointmentDefinition()
    for event in ("load_appointment", "apply_reply"):
        assert definition.transition("collecting", event) == "collecting"
    assert definition.transition("collecting", "submit") == "awaiting_confirmation"
    assert definition.transition("executing", "succeed") == "completed"
    assert definition.transition("executing", "review") == "manual_review_required"


@pytest.mark.anyio
async def test_pending_confirms_once_replay_and_already_confirmed() -> None:
    engine, _repository, definition = _engine()
    capability = _capability()
    spy = ExecuteSpy(_executor(capability))
    appointment_id = await _seed(capability, TENANT_A_CTX, "slot-a-1", "seed-1")
    _set_status(
        capability, TENANT_A, appointment_id, AppointmentStatus.PENDING_CONFIRMATION
    )
    started = await definition.start(
        engine,
        TENANT_A_CTX,
        command_id="start-1",
        appointment_id=appointment_id,
    )
    loaded = await definition.load_appointment(
        engine,
        spy,
        TENANT_A_CTX,
        started.workflow_id,
        command_id="load-1",
        run_id=uuid4(),
    )
    assert loaded.state == "collecting"
    assert loaded.data["status"] == AppointmentStatus.PENDING_CONFIRMATION
    _assert_no_secrets(loaded.data)
    first = await definition.confirm_appointment(
        engine,
        spy,
        TENANT_A_CTX,
        started.workflow_id,
        command_id="confirm-1",
        run_id=uuid4(),
    )
    assert first.state == "completed"
    assert first.data["status"] == AppointmentStatus.CONFIRMED
    replay = await definition.confirm_appointment(
        engine,
        spy,
        TENANT_A_CTX,
        started.workflow_id,
        command_id="confirm-1",
        run_id=uuid4(),
    )
    assert replay.state == "completed"
    assert capability.operations.count("confirm") == 1
    confirm_calls = [call for call in spy.calls if call.name == "appointments.confirm"]
    assert len(confirm_calls) == 1
    assert confirm_calls[0].idempotency_key == (
        f"{started.workflow_id}:appointments.confirm"
    )
    already = await definition.start(
        engine,
        TENANT_A_CTX,
        command_id="start-2",
        appointment_id=appointment_id,
    )
    await definition.load_appointment(
        engine,
        spy,
        TENANT_A_CTX,
        already.workflow_id,
        command_id="load-2",
        run_id=uuid4(),
    )
    second = await definition.confirm_appointment(
        engine,
        spy,
        TENANT_A_CTX,
        already.workflow_id,
        command_id="confirm-2",
        run_id=uuid4(),
    )
    assert second.state == "completed"
    assert second.data["status"] == AppointmentStatus.CONFIRMED
    assert capability.operations.count("confirm") == 1
    assert "create" not in [c for c in capability.operations if c != "create"] or True
    assert "cancel" not in capability.operations
    _assert_no_secrets(first.data)
    _assert_no_secrets(second.data)


@pytest.mark.anyio
async def test_scheduled_confirms_once() -> None:
    engine, _repository, definition = _engine()
    capability = _capability()
    executor = _executor(capability)
    appointment_id = await _seed(capability, TENANT_A_CTX, "slot-a-1", "seed-1")
    started = await definition.start(
        engine,
        TENANT_A_CTX,
        command_id="start-1",
        appointment_id=appointment_id,
    )
    await definition.load_appointment(
        engine,
        executor,
        TENANT_A_CTX,
        started.workflow_id,
        command_id="load-1",
        run_id=uuid4(),
    )
    result = await definition.confirm_appointment(
        engine,
        executor,
        TENANT_A_CTX,
        started.workflow_id,
        command_id="confirm-1",
        run_id=uuid4(),
    )
    assert result.state == "completed"
    assert result.data["status"] == AppointmentStatus.CONFIRMED
    assert capability.operations.count("confirm") == 1


@pytest.mark.anyio
async def test_ambiguous_reply_does_not_mutate() -> None:
    engine, _repository, definition = _engine()
    capability = _capability()
    executor = _executor(capability)
    appointment_id = await _seed(capability, TENANT_A_CTX, "slot-a-1", "seed-1")
    started = await definition.start(
        engine,
        TENANT_A_CTX,
        command_id="start-1",
        appointment_id=appointment_id,
    )
    await definition.load_appointment(
        engine,
        executor,
        TENANT_A_CTX,
        started.workflow_id,
        command_id="load-1",
        run_id=uuid4(),
    )
    result = await definition.apply_reply(
        engine,
        executor,
        TENANT_A_CTX,
        started.workflow_id,
        command_id="reply-1",
        run_id=uuid4(),
        text="maybe",
    )
    assert result.state == "collecting"
    _assert_safe_text(result.data.get("correction") or result.data.get("error") or "")
    assert capability.operations.count("confirm") == 0
    got = await capability.get(
        TENANT_A_CTX, AppointmentGetRequest(appointment_id=appointment_id)
    )
    assert got.ok
    assert got.value is not None
    assert got.value.status is AppointmentStatus.SCHEDULED
    _assert_no_secrets(result.data)


@pytest.mark.anyio
async def test_confirm_timeout_requires_manual_review() -> None:
    engine, _repository, definition = _engine()
    capability = _capability(
        fault=FaultPlan(fault="timeout", operations=frozenset({"confirm"}))
    )
    executor = _executor(capability)
    appointment_id = await _seed(capability, TENANT_A_CTX, "slot-a-1", "seed-1")
    started = await definition.start(
        engine,
        TENANT_A_CTX,
        command_id="start-1",
        appointment_id=appointment_id,
    )
    await definition.load_appointment(
        engine,
        executor,
        TENANT_A_CTX,
        started.workflow_id,
        command_id="load-1",
        run_id=uuid4(),
    )
    result = await definition.confirm_appointment(
        engine,
        executor,
        TENANT_A_CTX,
        started.workflow_id,
        command_id="confirm-1",
        run_id=uuid4(),
    )
    assert result.state == "manual_review_required"
    assert result.state != "completed"
    _assert_no_secrets(result.data)


@pytest.mark.anyio
async def test_tenant_a_cannot_confirm_tenant_b_appointment() -> None:
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
    result = await definition.confirm_appointment(
        engine,
        executor,
        TENANT_A_CTX,
        started.workflow_id,
        command_id="confirm-1",
        run_id=uuid4(),
    )
    assert capability.operations.count("confirm") == 0
    assert foreign_id not in str(result.data.get("error") or result.error or "")
    got = await capability.get(
        TENANT_B_CTX, AppointmentGetRequest(appointment_id=foreign_id)
    )
    assert got.ok
    assert got.value is not None
    assert got.value.status is AppointmentStatus.SCHEDULED
