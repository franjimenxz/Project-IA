from __future__ import annotations

import asyncio
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
from ia_mcp.mcp.audit import ToolAuditAdapter
from ia_mcp.mcp.executor import ToolExecutor
from ia_mcp.mcp.fakes.appointments import FakeAppointmentCapability, FaultPlan
from ia_mcp.tenancy.models import TenantContext
from ia_mcp.workflows.appointments.confirm import ConfirmAppointmentDefinition
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


def _capability(*, fault: FaultPlan | None = None) -> CountingCapability:
    return CountingCapability(
        clock=lambda: CLOCK,
        fault_plan=fault,
        initial_slots={
            TENANT_A: (
                _slot("slot-a-1", 13, token="tok-a-secret"),
                _slot("slot-a-2", 14, token="tok-a2-secret"),
            ),
            TENANT_B: (_slot("slot-b-1", 13, token="tok-b-secret"),),
        },
    )


def _executor(
    capability: FakeAppointmentCapability,
    skill: frozenset[str],
    audit: ToolAuditAdapter | None = None,
) -> ToolExecutor:
    return ToolExecutor(
        server=ALL_TOOLS,
        tenant=ALL_TOOLS,
        skill=skill,
        capability=capability,
        audit_hook=audit,
    )


def _reschedule_engine() -> tuple[
    WorkflowEngine, InMemoryWorkflowRepository, RescheduleAppointmentDefinition
]:
    repository = InMemoryWorkflowRepository()
    definition = RescheduleAppointmentDefinition()
    return WorkflowEngine(repository, definition), repository, definition


def _confirm_engine() -> tuple[
    WorkflowEngine, InMemoryWorkflowRepository, ConfirmAppointmentDefinition
]:
    repository = InMemoryWorkflowRepository()
    definition = ConfirmAppointmentDefinition()
    return WorkflowEngine(repository, definition), repository, definition


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


async def _prepare_reschedule(
    engine: WorkflowEngine,
    definition: RescheduleAppointmentDefinition,
    executor: ToolExecutor,
    appointment_id: str,
) -> UUID:
    started = await definition.start(
        engine, TENANT_A_CTX, command_id="start-1", appointment_id=appointment_id
    )
    await definition.load_appointment(
        engine,
        executor,
        TENANT_A_CTX,
        started.workflow_id,
        command_id="load-1",
        run_id=uuid4(),
    )
    await definition.search_slots(
        engine,
        executor,
        TENANT_A_CTX,
        started.workflow_id,
        command_id="search-1",
        run_id=uuid4(),
    )
    await definition.select_slot(
        engine,
        TENANT_A_CTX,
        started.workflow_id,
        command_id="select-1",
        slot_id="slot-a-2",
    )
    return started.workflow_id


@pytest.mark.anyio
@pytest.mark.resilience
async def test_timeout_before_send_does_not_reschedule() -> None:
    engine, _repository, definition = _reschedule_engine()
    capability = _capability()
    executor = _executor(capability, RESCHEDULE_TOOLS)
    original_id = await _seed(capability, TENANT_A_CTX, "slot-a-1", "seed-1")
    workflow_id = await _prepare_reschedule(engine, definition, executor, original_id)
    capability._fault_plan = FaultPlan(
        fault="timeout", operations=frozenset({"search"})
    )
    result = await definition.confirm_reschedule(
        engine,
        executor,
        TENANT_A_CTX,
        workflow_id,
        command_id="confirm-1",
        run_id=uuid4(),
    )
    assert result.state != "completed"
    assert capability.operations.count("reschedule") == 0
    got = await capability.get(
        TENANT_A_CTX, AppointmentGetRequest(appointment_id=original_id)
    )
    assert got.ok
    assert got.value is not None
    assert got.value.status is AppointmentStatus.SCHEDULED
    _assert_no_secrets(result.data)


@pytest.mark.anyio
@pytest.mark.resilience
async def test_timeout_after_send_requires_manual_review() -> None:
    engine, _repository, definition = _reschedule_engine()
    capability = _capability(
        fault=FaultPlan(fault="timeout", operations=frozenset({"reschedule"}))
    )
    executor = _executor(capability, RESCHEDULE_TOOLS)
    original_id = await _seed(capability, TENANT_A_CTX, "slot-a-1", "seed-1")
    workflow_id = await _prepare_reschedule(engine, definition, executor, original_id)
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
@pytest.mark.resilience
async def test_uncertain_malformed_reschedule_requires_manual_review() -> None:
    engine, _repository, definition = _reschedule_engine()
    capability = _capability(
        fault=FaultPlan(fault="malformed", operations=frozenset({"reschedule"}))
    )
    executor = _executor(capability, RESCHEDULE_TOOLS)
    original_id = await _seed(capability, TENANT_A_CTX, "slot-a-1", "seed-1")
    workflow_id = await _prepare_reschedule(engine, definition, executor, original_id)
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
@pytest.mark.resilience
async def test_concurrent_confirms_mutate_once() -> None:
    engine, _repository, definition = _confirm_engine()
    capability = _capability()
    executor = _executor(capability, CONFIRM_TOOLS)
    appointment_id = await _seed(capability, TENANT_A_CTX, "slot-a-1", "seed-1")
    started = await definition.start(
        engine, TENANT_A_CTX, command_id="start-1", appointment_id=appointment_id
    )
    await definition.load_appointment(
        engine,
        executor,
        TENANT_A_CTX,
        started.workflow_id,
        command_id="load-1",
        run_id=uuid4(),
    )
    run_id = uuid4()
    first, second = await asyncio.gather(
        definition.confirm_appointment(
            engine,
            executor,
            TENANT_A_CTX,
            started.workflow_id,
            command_id="confirm-a",
            run_id=run_id,
        ),
        definition.confirm_appointment(
            engine,
            executor,
            TENANT_A_CTX,
            started.workflow_id,
            command_id="confirm-b",
            run_id=run_id,
        ),
    )
    assert "completed" in {first.state, second.state}
    assert capability.operations.count("confirm") == 1
    _assert_no_secrets(first.data)
    _assert_no_secrets(second.data)


@pytest.mark.anyio
@pytest.mark.resilience
async def test_confirm_timeout_after_send_requires_manual_review() -> None:
    engine, _repository, definition = _confirm_engine()
    capability = _capability(
        fault=FaultPlan(fault="timeout", operations=frozenset({"confirm"}))
    )
    executor = _executor(capability, CONFIRM_TOOLS)
    appointment_id = await _seed(capability, TENANT_A_CTX, "slot-a-1", "seed-1")
    started = await definition.start(
        engine, TENANT_A_CTX, command_id="start-1", appointment_id=appointment_id
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
@pytest.mark.resilience
async def test_confirm_timeout_before_send_does_not_confirm() -> None:
    engine, _repository, definition = _confirm_engine()
    capability = _capability()
    executor = _executor(capability, CONFIRM_TOOLS)
    appointment_id = await _seed(capability, TENANT_A_CTX, "slot-a-1", "seed-1")
    started = await definition.start(
        engine, TENANT_A_CTX, command_id="start-1", appointment_id=appointment_id
    )
    await definition.load_appointment(
        engine,
        executor,
        TENANT_A_CTX,
        started.workflow_id,
        command_id="load-1",
        run_id=uuid4(),
    )
    capability._fault_plan = FaultPlan(fault="timeout", operations=frozenset({"get"}))
    result = await definition.confirm_appointment(
        engine,
        executor,
        TENANT_A_CTX,
        started.workflow_id,
        command_id="confirm-1",
        run_id=uuid4(),
    )
    assert result.state != "completed"
    assert capability.operations.count("confirm") == 0
    got = await capability.get(
        TENANT_A_CTX, AppointmentGetRequest(appointment_id=appointment_id)
    )
    # last get is faulted; reset and check appointment still scheduled
    capability._fault_plan = None
    got = await capability.get(
        TENANT_A_CTX, AppointmentGetRequest(appointment_id=appointment_id)
    )
    assert got.ok
    assert got.value is not None
    assert got.value.status is AppointmentStatus.SCHEDULED
    _assert_no_secrets(result.data)


@pytest.mark.anyio
@pytest.mark.resilience
async def test_cross_tenant_confirm_and_reschedule_leave_b_intact() -> None:
    confirm_engine, _cr, confirm_def = _confirm_engine()
    capability = _capability()
    confirm_exec = _executor(capability, CONFIRM_TOOLS)
    foreign_id = await _seed(capability, TENANT_B_CTX, "slot-b-1", "seed-b")
    started = await confirm_def.start(
        confirm_engine, TENANT_A_CTX, command_id="start-1", appointment_id=foreign_id
    )
    loaded = await confirm_def.load_appointment(
        confirm_engine,
        confirm_exec,
        TENANT_A_CTX,
        started.workflow_id,
        command_id="load-1",
        run_id=uuid4(),
    )
    error = str(loaded.data.get("error") or loaded.error or "")
    assert foreign_id not in error
    assert str(TENANT_B) not in error
    await confirm_def.confirm_appointment(
        confirm_engine,
        confirm_exec,
        TENANT_A_CTX,
        started.workflow_id,
        command_id="confirm-1",
        run_id=uuid4(),
    )
    reschedule_engine, _rr, reschedule_def = _reschedule_engine()
    reschedule_exec = _executor(capability, RESCHEDULE_TOOLS)
    started_r = await reschedule_def.start(
        reschedule_engine,
        TENANT_A_CTX,
        command_id="start-r",
        appointment_id=foreign_id,
    )
    await reschedule_def.load_appointment(
        reschedule_engine,
        reschedule_exec,
        TENANT_A_CTX,
        started_r.workflow_id,
        command_id="load-r",
        run_id=uuid4(),
    )
    await reschedule_def.confirm_reschedule(
        reschedule_engine,
        reschedule_exec,
        TENANT_A_CTX,
        started_r.workflow_id,
        command_id="confirm-r",
        run_id=uuid4(),
    )
    assert capability.operations.count("confirm") == 0
    assert capability.operations.count("reschedule") == 0
    got = await capability.get(
        TENANT_B_CTX, AppointmentGetRequest(appointment_id=foreign_id)
    )
    assert got.ok
    assert got.value is not None
    assert got.value.status is AppointmentStatus.SCHEDULED
