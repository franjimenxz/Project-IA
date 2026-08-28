from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from pydantic import SecretStr

from ia_mcp.configuration.models import AgentConfig, AppointmentPolicy, TenantConfig
from ia_mcp.contracts.appointments import AppointmentSearchRequest, AppointmentSlot
from ia_mcp.mcp.audit import ToolAuditAdapter
from ia_mcp.mcp.executor import ToolExecutor
from ia_mcp.mcp.fakes.appointments import FakeAppointmentCapability, FaultPlan
from ia_mcp.tenancy.models import TenantContext
from ia_mcp.workflows.appointments.create import CreateAppointmentDefinition
from ia_mcp.workflows.engine import WorkflowEngine
from tests.unit.workflows.fakes import InMemoryWorkflowRepository

TENANT_A = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
TENANT_A_CTX = TenantContext(
    tenant_id=TENANT_A,
    tenant_slug="tenant-a",
    config_version=1,
    correlation_id=UUID("33333333-3333-3333-3333-333333333333"),
)

CLOCK = datetime(2026, 9, 1, 12, tzinfo=UTC)
FIELDS_A = ("specialty", "date_from", "date_to")
VALID_A: dict[str, object] = {
    "specialty": "cardiologia",
    "date_from": "2026-09-01",
    "date_to": "2026-09-01",
}
PATIENT = {"name": "Ada Lovelace", "email": "ada@example.com"}
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
SEARCH_AND_CREATE = frozenset({"appointments.search", "appointments.create"})


def _config() -> TenantConfig:
    return TenantConfig(
        tenant_id=TENANT_A,
        version=1,
        agent=AgentConfig(tone="cordial"),
        enabled_skills=frozenset({"appointments"}),
        appointments=AppointmentPolicy(required_fields=FIELDS_A),
    )


def _slot() -> AppointmentSlot:
    return AppointmentSlot(
        slot_id="slot-a-1",
        starts_at=datetime(2026, 9, 1, 13, 0, tzinfo=UTC),
        ends_at=datetime(2026, 9, 1, 13, 30, tzinfo=UTC),
        specialty="cardiologia",
        practitioner="Dr. Ada",
        location="sede-centro",
        booking_token=SecretStr("tok-a-secret"),
    )


class CountingCapability(FakeAppointmentCapability):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.operations: list[str] = []

    async def search(self, tenant: TenantContext, request: AppointmentSearchRequest):
        self.operations.append("search")
        return await super().search(tenant, request)

    async def create(self, tenant: TenantContext, request: Any, idempotency_key: str):
        self.operations.append("create")
        return await super().create(tenant, request, idempotency_key)


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


def _engine() -> tuple[
    WorkflowEngine, InMemoryWorkflowRepository, CreateAppointmentDefinition
]:
    repository = InMemoryWorkflowRepository()
    definition = CreateAppointmentDefinition()
    return WorkflowEngine(repository, definition), repository, definition


def _executor(
    capability: FakeAppointmentCapability, audit: ToolAuditAdapter | None = None
) -> ToolExecutor:
    return ToolExecutor(
        server=ALL_TOOLS,
        tenant=ALL_TOOLS,
        skill=SEARCH_AND_CREATE,
        capability=capability,
        audit_hook=audit,
    )


async def _collect_and_select(
    engine: WorkflowEngine,
    definition: CreateAppointmentDefinition,
    executor: ToolExecutor,
    config: TenantConfig,
    *,
    capability: CountingCapability,
) -> UUID:
    del capability
    started = await definition.start(
        engine, TENANT_A_CTX, command_id="start-1", config=config
    )
    await definition.collect_fields(
        engine,
        TENANT_A_CTX,
        started.workflow_id,
        command_id="collect-1",
        fields=VALID_A,
        config=config,
    )
    await definition.search_slots(
        engine,
        executor,
        TENANT_A_CTX,
        started.workflow_id,
        command_id="search-1",
        run_id=uuid4(),
        config=config,
    )
    await definition.select_slot(
        engine,
        TENANT_A_CTX,
        started.workflow_id,
        command_id="select-1",
        slot_id="slot-a-1",
    )
    return started.workflow_id


@pytest.mark.anyio
@pytest.mark.resilience
async def test_lost_slot_does_not_create_or_complete() -> None:
    engine, _repository, definition = _engine()
    config = _config()
    capability = CountingCapability(
        clock=lambda: CLOCK, initial_slots={TENANT_A: (_slot(),)}
    )
    executor = _executor(capability)
    workflow_id = await _collect_and_select(
        engine, definition, executor, config, capability=capability
    )
    capability._agendas[TENANT_A].slots.clear()
    creates_before = capability.operations.count("create")
    result = await definition.confirm_create(
        engine,
        executor,
        TENANT_A_CTX,
        workflow_id,
        command_id="confirm-1",
        run_id=uuid4(),
        config=config,
        patient=PATIENT,
    )
    assert result.state != "completed"
    assert result.data.get("phase") == "awaiting_slot_selection"
    assert capability.operations.count("create") == creates_before
    _assert_no_secrets(result.data)


@pytest.mark.anyio
@pytest.mark.resilience
async def test_timeout_after_send_requires_manual_review() -> None:
    engine, _repository, definition = _engine()
    config = _config()
    capability = CountingCapability(
        clock=lambda: CLOCK,
        initial_slots={TENANT_A: (_slot(),)},
        fault_plan=FaultPlan(fault="timeout", operations=frozenset({"create"})),
    )
    executor = _executor(capability)
    workflow_id = await _collect_and_select(
        engine, definition, executor, config, capability=capability
    )
    result = await definition.confirm_create(
        engine,
        executor,
        TENANT_A_CTX,
        workflow_id,
        command_id="confirm-1",
        run_id=uuid4(),
        config=config,
        patient=PATIENT,
    )
    assert result.state == "manual_review_required"
    assert result.state != "completed"
    assert capability.operations.count("create") in {0, 1}
    assert result.data.get("appointment_id") in (None, "")
    _assert_no_secrets(result.data)


@pytest.mark.anyio
@pytest.mark.resilience
async def test_timeout_before_send_does_not_create() -> None:
    engine, _repository, definition = _engine()
    config = _config()
    capability = CountingCapability(
        clock=lambda: CLOCK, initial_slots={TENANT_A: (_slot(),)}
    )
    executor = _executor(capability)
    workflow_id = await _collect_and_select(
        engine, definition, executor, config, capability=capability
    )
    capability._fault_plan = FaultPlan(
        fault="timeout", operations=frozenset({"search"})
    )
    result = await definition.confirm_create(
        engine,
        executor,
        TENANT_A_CTX,
        workflow_id,
        command_id="confirm-1",
        run_id=uuid4(),
        config=config,
        patient=PATIENT,
    )
    assert result.state != "completed"
    assert capability.operations.count("create") == 0
    _assert_no_secrets(result.data)


@pytest.mark.anyio
@pytest.mark.resilience
async def test_malformed_create_requires_manual_review() -> None:
    engine, _repository, definition = _engine()
    config = _config()
    capability = CountingCapability(
        clock=lambda: CLOCK,
        initial_slots={TENANT_A: (_slot(),)},
        fault_plan=FaultPlan(fault="malformed", operations=frozenset({"create"})),
    )
    executor = _executor(capability)
    workflow_id = await _collect_and_select(
        engine, definition, executor, config, capability=capability
    )
    result = await definition.confirm_create(
        engine,
        executor,
        TENANT_A_CTX,
        workflow_id,
        command_id="confirm-1",
        run_id=uuid4(),
        config=config,
        patient=PATIENT,
    )
    assert result.state == "manual_review_required"
    assert result.state != "completed"
    _assert_no_secrets(result.data)


@pytest.mark.anyio
@pytest.mark.resilience
async def test_audit_adapter_strips_booking_secrets() -> None:
    engine, _repository, definition = _engine()
    config = _config()
    capability = CountingCapability(
        clock=lambda: CLOCK, initial_slots={TENANT_A: (_slot(),)}
    )
    audit = ToolAuditAdapter()
    executor = _executor(capability, audit=audit)
    workflow_id = await _collect_and_select(
        engine, definition, executor, config, capability=capability
    )
    result = await definition.confirm_create(
        engine,
        executor,
        TENANT_A_CTX,
        workflow_id,
        command_id="confirm-1",
        run_id=uuid4(),
        config=config,
        patient=PATIENT,
    )
    assert result.state == "completed"
    blob = repr(audit.executions)
    assert "tok-a-secret" not in blob
    assert "booking_token" not in blob
    for execution in audit.executions:
        blob = repr(execution)
        assert "tok-a-secret" not in blob
        assert "booking_token" not in blob
        if execution.summary is not None:
            _assert_no_secrets(dict(execution.summary))
