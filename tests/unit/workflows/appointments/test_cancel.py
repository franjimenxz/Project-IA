from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from pydantic import SecretStr

from ia_mcp.configuration.models import AgentConfig, AppointmentPolicy, TenantConfig
from ia_mcp.contracts.appointments import (
    AppointmentCancelRequest,
    AppointmentCreateRequest,
    AppointmentSlot,
    AppointmentStatus,
    PatientRef,
)
from ia_mcp.mcp.executor import ToolExecutor
from ia_mcp.mcp.fakes.appointments import FakeAppointmentCapability, FaultPlan
from ia_mcp.tenancy.models import TenantContext
from ia_mcp.workflows.appointments.cancel import CancelAppointmentDefinition
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
GET_AND_CANCEL = frozenset({"appointments.get", "appointments.cancel"})


def _config(
    tenant_id: UUID, *, enabled: frozenset[str] | None = None
) -> TenantConfig:
    skills: frozenset[str] = (
        frozenset({"appointments"}) if enabled is None else enabled
    )
    return TenantConfig(
        tenant_id=tenant_id,
        version=1,
        agent=AgentConfig(tone="cordial"),
        enabled_skills=skills,  # type: ignore[arg-type]
        appointments=AppointmentPolicy(),
    )


def _slot_a() -> AppointmentSlot:
    return AppointmentSlot(
        slot_id="slot-a-1",
        starts_at=datetime(2026, 9, 1, 13, 0, tzinfo=UTC),
        ends_at=datetime(2026, 9, 1, 13, 30, tzinfo=UTC),
        specialty="cardiologia",
        practitioner="Dr. Ada",
        location="sede-centro",
        booking_token=SecretStr("tok-a-secret"),
    )


def _slot_b() -> AppointmentSlot:
    return AppointmentSlot(
        slot_id="slot-b-1",
        starts_at=datetime(2026, 9, 1, 13, 0, tzinfo=UTC),
        ends_at=datetime(2026, 9, 1, 13, 30, tzinfo=UTC),
        specialty="cardiologia",
        practitioner="Dr. Bravo Exclusive",
        location="sede-norte-b",
        booking_token=SecretStr("tok-b-secret"),
    )


class CountingCapability(FakeAppointmentCapability):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.operations: list[str] = []

    async def get(self, tenant: TenantContext, request: Any):
        self.operations.append("get")
        return await super().get(tenant, request)

    async def create(self, tenant: TenantContext, request: Any, idempotency_key: str):
        self.operations.append("create")
        return await super().create(tenant, request, idempotency_key)

    async def cancel(self, tenant: TenantContext, request: Any, idempotency_key: str):
        self.operations.append("cancel")
        return await super().cancel(tenant, request, idempotency_key)


def _capability(
    *,
    id_factory: Any | None = None,
    fault: FaultPlan | None = None,
) -> CountingCapability:
    return CountingCapability(
        clock=lambda: CLOCK,
        id_factory=id_factory or (lambda: "appt-a-1"),
        fault_plan=fault,
        initial_slots={TENANT_A: (_slot_a(),), TENANT_B: (_slot_b(),)},
    )


def _executor(
    capability: FakeAppointmentCapability,
    *,
    skill_tools: frozenset[str] = GET_AND_CANCEL,
) -> ToolExecutor:
    return ToolExecutor(
        server=ALL_TOOLS,
        tenant=ALL_TOOLS,
        skill=skill_tools,
        capability=capability,
    )


def _engine() -> tuple[
    WorkflowEngine, InMemoryWorkflowRepository, CancelAppointmentDefinition
]:
    repository = InMemoryWorkflowRepository()
    definition = CancelAppointmentDefinition()
    return WorkflowEngine(repository, definition), repository, definition


def _assert_safe_text(value: object) -> str:
    assert isinstance(value, str)
    assert value
    lowered = value.lower()
    assert "traceback" not in lowered
    assert "tok-a-secret" not in lowered
    assert "tok-b-secret" not in lowered
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
    assert "tok-b-secret" not in text
    assert "booking_token" not in text


async def _book(
    capability: CountingCapability,
    tenant: TenantContext,
    *,
    slot_id: str,
    token: str,
    key: str,
) -> str:
    result = await capability.create(
        tenant,
        AppointmentCreateRequest(
            slot_id=slot_id,
            booking_token=SecretStr(token),
            patient=PATIENT,
        ),
        idempotency_key=key,
    )
    assert result.ok
    assert result.value is not None
    return result.value.appointment_id


def _status(
    capability: CountingCapability, tenant: TenantContext, appointment_id: str
) -> AppointmentStatus:
    return capability._agenda(tenant).appointments[appointment_id].status


@pytest.mark.anyio
async def test_happy_path_cancels_appointment() -> None:
    engine, _repository, definition = _engine()
    capability = _capability()
    executor = _executor(capability)
    config = _config(TENANT_A)
    appointment_id = await _book(
        capability, TENANT_A_CTX, slot_id="slot-a-1", token="tok-a-secret", key="seed-a"
    )
    capability.operations.clear()
    started = await definition.start(
        engine,
        TENANT_A_CTX,
        command_id="start-1",
        config=config,
        appointment_id=appointment_id,
    )
    assert started.type == "cancel_appointment"
    assert started.state == "collecting"
    looked = await definition.lookup(
        engine,
        executor,
        TENANT_A_CTX,
        started.workflow_id,
        command_id="lookup-1",
        run_id=uuid4(),
        config=config,
    )
    assert looked.state == "awaiting_confirmation"
    confirmed = await definition.confirm_cancel(
        engine,
        executor,
        TENANT_A_CTX,
        started.workflow_id,
        command_id="confirm-1",
        run_id=uuid4(),
        config=config,
        confirmed=True,
    )
    assert confirmed.state == "completed"
    assert confirmed.data["appointment_id"] == appointment_id
    assert _status(capability, TENANT_A_CTX, appointment_id) is AppointmentStatus.CANCELLED
    assert capability.operations.count("get") == 1
    assert capability.operations.count("cancel") == 1
    _assert_no_secrets(confirmed.data)
    _assert_no_secrets(looked.data)


@pytest.mark.anyio
async def test_replay_same_command_does_not_cancel_twice() -> None:
    engine, _repository, definition = _engine()
    capability = _capability()
    executor = _executor(capability)
    config = _config(TENANT_A)
    appointment_id = await _book(
        capability, TENANT_A_CTX, slot_id="slot-a-1", token="tok-a-secret", key="seed-a"
    )
    capability.operations.clear()
    started = await definition.start(
        engine,
        TENANT_A_CTX,
        command_id="start-1",
        config=config,
        appointment_id=appointment_id,
    )
    await definition.lookup(
        engine,
        executor,
        TENANT_A_CTX,
        started.workflow_id,
        command_id="lookup-1",
        run_id=uuid4(),
        config=config,
    )
    run_id = uuid4()
    first = await definition.confirm_cancel(
        engine,
        executor,
        TENANT_A_CTX,
        started.workflow_id,
        command_id="confirm-1",
        run_id=run_id,
        config=config,
        confirmed=True,
    )
    replay = await definition.confirm_cancel(
        engine,
        executor,
        TENANT_A_CTX,
        started.workflow_id,
        command_id="confirm-1",
        run_id=run_id,
        config=config,
        confirmed=True,
    )
    second = await definition.confirm_cancel(
        engine,
        executor,
        TENANT_A_CTX,
        started.workflow_id,
        command_id="confirm-2",
        run_id=run_id,
        config=config,
        confirmed=True,
    )
    assert first.state == "completed"
    assert replay.state == "completed"
    assert second.state == "completed"
    assert first.data["appointment_id"] == appointment_id
    assert replay.data["appointment_id"] == appointment_id
    assert second.data["appointment_id"] == appointment_id
    assert capability.operations.count("cancel") == 1
    assert _status(capability, TENANT_A_CTX, appointment_id) is AppointmentStatus.CANCELLED


@pytest.mark.anyio
async def test_already_cancelled_is_idempotent_success() -> None:
    engine, _repository, definition = _engine()
    capability = _capability()
    executor = _executor(capability)
    config = _config(TENANT_A)
    appointment_id = await _book(
        capability, TENANT_A_CTX, slot_id="slot-a-1", token="tok-a-secret", key="seed-a"
    )
    pre = await capability.cancel(
        TENANT_A_CTX,
        AppointmentCancelRequest(appointment_id=appointment_id),
        idempotency_key="pre-cancel",
    )
    assert pre.ok
    capability.operations.clear()
    started = await definition.start(
        engine,
        TENANT_A_CTX,
        command_id="start-1",
        config=config,
        appointment_id=appointment_id,
    )
    looked = await definition.lookup(
        engine,
        executor,
        TENANT_A_CTX,
        started.workflow_id,
        command_id="lookup-1",
        run_id=uuid4(),
        config=config,
    )
    assert looked.state == "awaiting_confirmation"
    assert looked.data.get("already_cancelled") is True
    confirmed = await definition.confirm_cancel(
        engine,
        executor,
        TENANT_A_CTX,
        started.workflow_id,
        command_id="confirm-1",
        run_id=uuid4(),
        config=config,
        confirmed=True,
    )
    assert confirmed.state == "completed"
    assert confirmed.error is None
    assert capability.operations.count("cancel") <= 1
    assert _status(capability, TENANT_A_CTX, appointment_id) is AppointmentStatus.CANCELLED
    _assert_no_secrets(confirmed.data)


@pytest.mark.anyio
async def test_confirm_denied_leaves_appointment_scheduled() -> None:
    engine, _repository, definition = _engine()
    capability = _capability()
    executor = _executor(capability)
    config = _config(TENANT_A)
    appointment_id = await _book(
        capability, TENANT_A_CTX, slot_id="slot-a-1", token="tok-a-secret", key="seed-a"
    )
    capability.operations.clear()
    started = await definition.start(
        engine,
        TENANT_A_CTX,
        command_id="start-1",
        config=config,
        appointment_id=appointment_id,
    )
    await definition.lookup(
        engine,
        executor,
        TENANT_A_CTX,
        started.workflow_id,
        command_id="lookup-1",
        run_id=uuid4(),
        config=config,
    )
    denied = await definition.confirm_cancel(
        engine,
        executor,
        TENANT_A_CTX,
        started.workflow_id,
        command_id="deny-1",
        run_id=uuid4(),
        config=config,
        confirmed=False,
    )
    assert denied.state == "cancelled"
    assert _status(capability, TENANT_A_CTX, appointment_id) is AppointmentStatus.SCHEDULED
    assert capability.operations == ["get"]
    assert "cancel" not in capability.operations


@pytest.mark.anyio
async def test_policy_disabled_does_not_call_capability() -> None:
    engine, _repository, definition = _engine()
    capability = _capability()
    executor = _executor(capability)
    config = _config(TENANT_A, enabled=frozenset())
    appointment_id = await _book(
        capability, TENANT_A_CTX, slot_id="slot-a-1", token="tok-a-secret", key="seed-a"
    )
    capability.operations.clear()
    started = await definition.start(
        engine,
        TENANT_A_CTX,
        command_id="start-1",
        config=config,
        appointment_id=appointment_id,
    )
    looked = await definition.lookup(
        engine,
        executor,
        TENANT_A_CTX,
        started.workflow_id,
        command_id="lookup-1",
        run_id=uuid4(),
        config=config,
    )
    assert looked.state == "failed"
    assert capability.operations == []
    _assert_safe_text(str(looked.data.get("error") or looked.error))
    _assert_no_secrets(looked.data)
    blob = repr(looked.data) + repr(looked.error)
    assert "traceback" not in blob.lower()
    assert str(TENANT_A) not in blob
    assert str(TENANT_B) not in blob
    assert _status(capability, TENANT_A_CTX, appointment_id) is AppointmentStatus.SCHEDULED


@pytest.mark.anyio
async def test_tenant_a_cannot_see_or_cancel_tenant_b_appointment() -> None:
    engine, _repository, definition = _engine()
    capability = _capability(id_factory=lambda: "appt-b-1")
    executor = _executor(capability)
    config_a = _config(TENANT_A)
    booked_b = await _book(
        capability, TENANT_B_CTX, slot_id="slot-b-1", token="tok-b-secret", key="seed-b"
    )
    assert booked_b == "appt-b-1"
    capability.operations.clear()
    started = await definition.start(
        engine,
        TENANT_A_CTX,
        command_id="start-1",
        config=config_a,
        appointment_id="appt-b-1",
    )
    looked = await definition.lookup(
        engine,
        executor,
        TENANT_A_CTX,
        started.workflow_id,
        command_id="lookup-1",
        run_id=uuid4(),
        config=config_a,
    )
    missing_started = await definition.start(
        engine,
        TENANT_A_CTX,
        command_id="start-missing",
        config=config_a,
        appointment_id="appt-missing-id",
    )
    missing = await definition.lookup(
        engine,
        executor,
        TENANT_A_CTX,
        missing_started.workflow_id,
        command_id="lookup-missing",
        run_id=uuid4(),
        config=config_a,
    )
    assert looked.state == "failed"
    assert missing.state == "failed"
    assert looked.data.get("error") == missing.data.get("error")
    assert looked.error == missing.error
    _assert_safe_text(str(looked.data.get("error") or looked.error))
    blob = repr(looked.data) + repr(looked.error)
    assert str(TENANT_B) not in blob
    assert "Dr. Bravo Exclusive" not in blob
    assert "sede-norte-b" not in blob
    assert "tok-b-secret" not in blob
    assert "cancel" not in capability.operations
    assert _status(capability, TENANT_B_CTX, "appt-b-1") is AppointmentStatus.SCHEDULED


@pytest.mark.anyio
async def test_cancel_timeout_goes_to_manual_review() -> None:
    engine, repository, definition = _engine()
    capability = _capability(
        fault=FaultPlan(fault="timeout", operations=frozenset({"cancel"}))
    )
    executor = _executor(capability)
    config = _config(TENANT_A)
    appointment_id = await _book(
        capability, TENANT_A_CTX, slot_id="slot-a-1", token="tok-a-secret", key="seed-a"
    )
    capability.operations.clear()
    started = await definition.start(
        engine,
        TENANT_A_CTX,
        command_id="start-1",
        config=config,
        appointment_id=appointment_id,
    )
    await definition.lookup(
        engine,
        executor,
        TENANT_A_CTX,
        started.workflow_id,
        command_id="lookup-1",
        run_id=uuid4(),
        config=config,
    )
    confirmed = await definition.confirm_cancel(
        engine,
        executor,
        TENANT_A_CTX,
        started.workflow_id,
        command_id="confirm-1",
        run_id=uuid4(),
        config=config,
        confirmed=True,
    )
    assert confirmed.state == "manual_review_required"
    assert confirmed.error == "upstream_timeout"
    _assert_safe_text(str(confirmed.data.get("error") or confirmed.error))
    _assert_no_secrets(confirmed.data)
    assert _status(capability, TENANT_A_CTX, appointment_id) is AppointmentStatus.SCHEDULED
    loaded = await repository.get(TENANT_A_CTX, started.workflow_id)
    assert loaded is not None
    assert loaded.error == "upstream_timeout"


@pytest.mark.anyio
async def test_concurrent_confirms_cancel_once() -> None:
    engine, _repository, definition = _engine()
    capability = _capability()
    executor = _executor(capability)
    config = _config(TENANT_A)
    appointment_id = await _book(
        capability, TENANT_A_CTX, slot_id="slot-a-1", token="tok-a-secret", key="seed-a"
    )
    capability.operations.clear()
    started = await definition.start(
        engine,
        TENANT_A_CTX,
        command_id="start-1",
        config=config,
        appointment_id=appointment_id,
    )
    await definition.lookup(
        engine,
        executor,
        TENANT_A_CTX,
        started.workflow_id,
        command_id="lookup-1",
        run_id=uuid4(),
        config=config,
    )
    run_id = uuid4()
    first, second = await asyncio.gather(
        definition.confirm_cancel(
            engine,
            executor,
            TENANT_A_CTX,
            started.workflow_id,
            command_id="confirm-a",
            run_id=run_id,
            config=config,
            confirmed=True,
        ),
        definition.confirm_cancel(
            engine,
            executor,
            TENANT_A_CTX,
            started.workflow_id,
            command_id="confirm-b",
            run_id=run_id,
            config=config,
            confirmed=True,
        ),
    )
    ids = {first.data.get("appointment_id"), second.data.get("appointment_id")}
    assert len(ids) == 1
    assert ids.pop() == appointment_id
    assert capability.operations.count("cancel") == 1
    assert "completed" in {first.state, second.state}
    assert {first.state, second.state} <= {
        "completed",
        "failed",
        "manual_review_required",
        "cancelled",
        "executing",
        "awaiting_confirmation",
    }
    assert _status(capability, TENANT_A_CTX, appointment_id) is AppointmentStatus.CANCELLED
    _assert_no_secrets(first.data)
    _assert_no_secrets(second.data)


@pytest.mark.anyio
async def test_missing_appointment_fails_not_found() -> None:
    engine, _repository, definition = _engine()
    capability = _capability()
    executor = _executor(capability)
    config = _config(TENANT_A)
    capability.operations.clear()
    started = await definition.start(
        engine,
        TENANT_A_CTX,
        command_id="start-1",
        config=config,
        appointment_id="appt-unknown",
    )
    looked = await definition.lookup(
        engine,
        executor,
        TENANT_A_CTX,
        started.workflow_id,
        command_id="lookup-1",
        run_id=uuid4(),
        config=config,
    )
    assert looked.state == "failed"
    _assert_safe_text(str(looked.data.get("error") or looked.error))
    assert "cancel" not in capability.operations
    assert looked.error == "not_found"


def test_lookup_events_keep_collecting() -> None:
    definition = CancelAppointmentDefinition()
    for event in ("lookup", "get_appointment"):
        assert definition.transition("collecting", event) == "collecting"
