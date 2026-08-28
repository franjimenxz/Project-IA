from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from pydantic import SecretStr

from ia_mcp.configuration.models import AgentConfig, AppointmentPolicy, TenantConfig
from ia_mcp.contracts.appointments import AppointmentSearchRequest, AppointmentSlot
from ia_mcp.mcp.executor import McpTarget, ToolAuditEvent, ToolCall, ToolExecutor
from ia_mcp.mcp.fakes.appointments import FakeAppointmentCapability, FaultPlan
from ia_mcp.skills.appointments import AppointmentSkill
from ia_mcp.tenancy.models import TenantContext
from ia_mcp.workflows.appointments.create import CreateAppointmentDefinition
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
SEARCH_ONLY = frozenset({"appointments.search"})
FIELDS_A = ("specialty", "date_from", "date_to")
FIELDS_B = ("specialty", "practitioner", "date_from", "date_to", "coverage")
VALID_A: dict[str, object] = {
    "specialty": "cardiologia",
    "date_from": "2026-09-01",
    "date_to": "2026-09-01",
}
VALID_B: dict[str, object] = {
    "specialty": "cardiologia",
    "practitioner": "Dr. Ada",
    "date_from": "2026-09-01",
    "date_to": "2026-09-01",
    "coverage": "osde",
}


def _config(tenant_id: UUID, required: tuple[str, ...]) -> TenantConfig:
    return TenantConfig(
        tenant_id=tenant_id,
        version=1,
        agent=AgentConfig(tone="cordial"),
        enabled_skills=frozenset({"appointments"}),
        appointments=AppointmentPolicy(required_fields=required),
    )


def _slot(*, token: str = "tok-a-secret") -> AppointmentSlot:
    return AppointmentSlot(
        slot_id="slot-a-1",
        starts_at=datetime(2026, 9, 1, 13, 0, tzinfo=UTC),
        ends_at=datetime(2026, 9, 1, 13, 30, tzinfo=UTC),
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

    async def create(self, tenant: TenantContext, request: Any, idempotency_key: str):
        self.operations.append("create")
        return await super().create(tenant, request, idempotency_key)

    async def cancel(self, tenant: TenantContext, request: Any, idempotency_key: str):
        self.operations.append("cancel")
        return await super().cancel(tenant, request, idempotency_key)


class ExecuteSpy:
    def __init__(self, inner: ToolExecutor) -> None:
        self.inner = inner
        self.calls: list[ToolCall] = []

    async def execute(
        self, tenant: TenantContext, run_id: UUID, call: ToolCall
    ) -> Any:
        self.calls.append(call)
        return await self.inner.execute(tenant, run_id, call)


class TenantResolver:
    async def resolve(self, tenant: TenantContext, capability: str) -> McpTarget:
        del capability
        server_id = "mcp-a" if tenant.tenant_id == TENANT_A else "mcp-b"
        return McpTarget(server_id=server_id, allowed_tools=SEARCH_ONLY)


def _capability(
    *,
    slots: Mapping[UUID, tuple[AppointmentSlot, ...]] | None = None,
    fault: FaultPlan | None = None,
) -> CountingCapability:
    default = {TENANT_A: (_slot(),), TENANT_B: (_slot(),)}
    return CountingCapability(
        clock=lambda: CLOCK,
        fault_plan=fault,
        initial_slots=slots if slots is not None else default,
    )


def _executor(
    capability: FakeAppointmentCapability,
    *,
    tenant_tools: frozenset[str] = ALL_TOOLS,
    skill_tools: frozenset[str] = SEARCH_ONLY,
    resolver: TenantResolver | None = None,
    audit: list[ToolAuditEvent] | None = None,
) -> ToolExecutor:
    hook = None if audit is None else audit.append
    return ToolExecutor(
        server=ALL_TOOLS,
        tenant=tenant_tools,
        skill=skill_tools,
        capability=capability,
        resolver=resolver,
        audit_hook=hook,
    )


def _engine() -> tuple[
    WorkflowEngine, InMemoryWorkflowRepository, CreateAppointmentDefinition
]:
    repository = InMemoryWorkflowRepository()
    definition = CreateAppointmentDefinition()
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


@pytest.mark.anyio
async def test_start_persists_create_appointment_collecting_fields() -> None:
    engine, repository, definition = _engine()
    config = _config(TENANT_A, FIELDS_A)
    started = await definition.start(
        engine, TENANT_A_CTX, command_id="start-1", config=config
    )
    assert started.type == "create_appointment"
    assert started.state == "collecting"
    assert started.data["phase"] == "collecting_fields"
    loaded = await repository.get(TENANT_A_CTX, started.workflow_id)
    assert loaded is not None
    assert loaded.type == "create_appointment"
    assert loaded.state == "collecting"
    assert loaded.data["phase"] == "collecting_fields"


@pytest.mark.parametrize(
    ("tenant_id", "required", "unexpected"),
    [
        (TENANT_A, FIELDS_A, ("practitioner", "coverage")),
        (TENANT_B, FIELDS_B, ()),
    ],
    ids=["tenant-a", "tenant-b"],
)
def test_requested_fields_follow_tenant_policy(
    tenant_id: UUID, required: tuple[str, ...], unexpected: tuple[str, ...]
) -> None:
    config = _config(tenant_id, required)
    definition = CreateAppointmentDefinition()
    skill = AppointmentSkill()
    requested = tuple(spec.name for spec in definition.requested_fields(config))
    skill_fields = tuple(spec.name for spec in skill.required_fields(config))
    assert requested == required
    assert skill_fields == required
    assert all(spec.required for spec in definition.requested_fields(config))
    for name in unexpected:
        assert name not in requested
        assert name not in skill_fields


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("required", "fields"),
    [
        (FIELDS_A, {"specialty": "", "date_from": "2026-09-01", "date_to": "2026-09-01"}),
        (
            FIELDS_A,
            {
                "specialty": "cardiologia",
                "date_from": "2026-09-10",
                "date_to": "2026-09-01",
            },
        ),
        (
            FIELDS_B,
            {
                "specialty": "cardiologia",
                "date_from": "2026-09-01",
                "date_to": "2026-09-01",
                "coverage": "osde",
            },
        ),
    ],
    ids=["empty-specialty", "inverted-dates", "missing-practitioner"],
)
async def test_invalid_fields_stay_collecting_with_safe_correction(
    required: tuple[str, ...], fields: dict[str, object]
) -> None:
    engine, repository, definition = _engine()
    tenant = TENANT_A_CTX if required == FIELDS_A else TENANT_B_CTX
    config = _config(tenant.tenant_id, required)
    started = await definition.start(
        engine, tenant, command_id="start-1", config=config
    )
    result = await definition.collect_fields(
        engine,
        tenant,
        started.workflow_id,
        command_id="collect-1",
        fields=fields,
        config=config,
    )
    assert result.state == "collecting"
    assert result.data["phase"] == "collecting_fields"
    _assert_safe_text(result.data["correction"])
    loaded = await repository.get(tenant, started.workflow_id)
    assert loaded is not None
    assert loaded.state == "collecting"
    assert loaded.data["phase"] == "collecting_fields"


@pytest.mark.anyio
async def test_valid_a_fields_then_search_uses_canonical_tool() -> None:
    engine, _repository, definition = _engine()
    config = _config(TENANT_A, FIELDS_A)
    capability = _capability()
    audit: list[ToolAuditEvent] = []
    executor = ExecuteSpy(_executor(capability, audit=audit))
    started = await definition.start(
        engine, TENANT_A_CTX, command_id="start-1", config=config
    )
    collected = await definition.collect_fields(
        engine,
        TENANT_A_CTX,
        started.workflow_id,
        command_id="collect-1",
        fields=VALID_A,
        config=config,
    )
    assert collected.data["phase"] == "collecting_fields"
    assert collected.state == "collecting"
    searched = await definition.search_slots(
        engine,
        executor,
        TENANT_A_CTX,
        started.workflow_id,
        command_id="search-1",
        run_id=uuid4(),
        config=config,
    )
    assert searched.state == "collecting"
    assert searched.data["phase"] == "awaiting_slot_selection"
    assert capability.operations == ["search"]
    assert [call.name for call in executor.calls] == ["appointments.search"]
    request = capability.last_request
    assert request is not None
    assert request.specialty == "cardiologia"
    assert request.date_from == date(2026, 9, 1)
    assert request.date_to == date(2026, 9, 1)
    assert request.practitioner is None
    assert request.coverage is None
    assert "create" not in capability.operations
    assert "cancel" not in capability.operations
    assert {event.tool for event in audit} == {"appointments.search"}


@pytest.mark.anyio
async def test_presented_slots_and_workflow_data_omit_booking_token() -> None:
    engine, repository, definition = _engine()
    config = _config(TENANT_A, FIELDS_A)
    raw_slot = _slot(token="tok-a-secret")
    capability = _capability(slots={TENANT_A: (raw_slot,)})
    executor = _executor(capability)
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
    searched = await definition.search_slots(
        engine,
        executor,
        TENANT_A_CTX,
        started.workflow_id,
        command_id="search-1",
        run_id=uuid4(),
        config=config,
    )
    presented = definition.present_slots((raw_slot,))
    blob = repr(searched.data) + repr(presented)
    assert "booking_token" not in blob
    assert "tok-a-secret" not in blob
    _assert_no_secrets(searched.data)
    _assert_no_secrets(presented)
    loaded = await repository.get(TENANT_A_CTX, started.workflow_id)
    assert loaded is not None
    _assert_no_secrets(dict(loaded.data))
    assert searched.data["phase"] == "awaiting_slot_selection"


@pytest.mark.anyio
async def test_empty_slots_are_a_valid_search_outcome() -> None:
    engine, _repository, definition = _engine()
    config = _config(TENANT_A, FIELDS_A)
    capability = _capability(slots={TENANT_A: ()})
    executor = _executor(capability)
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
    searched = await definition.search_slots(
        engine,
        executor,
        TENANT_A_CTX,
        started.workflow_id,
        command_id="search-1",
        run_id=uuid4(),
        config=config,
    )
    assert searched.data["phase"] == "awaiting_slot_selection"
    assert searched.data["slots"] == []
    assert definition.present_slots([]) == []


@pytest.mark.anyio
async def test_timeout_does_not_await_slot_selection() -> None:
    engine, repository, definition = _engine()
    config = _config(TENANT_A, FIELDS_A)
    capability = _capability(
        fault=FaultPlan(fault="timeout", operations=frozenset({"search"}))
    )
    executor = _executor(capability)
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
    searched = await definition.search_slots(
        engine,
        executor,
        TENANT_A_CTX,
        started.workflow_id,
        command_id="search-1",
        run_id=uuid4(),
        config=config,
    )
    assert searched.state == "collecting"
    assert searched.data["phase"] != "awaiting_slot_selection"
    _assert_safe_text(searched.data["error"])
    loaded = await repository.get(TENANT_A_CTX, started.workflow_id)
    assert loaded is not None
    assert loaded.state == "collecting"
    assert loaded.data["phase"] != "awaiting_slot_selection"


@pytest.mark.anyio
async def test_disabled_search_does_not_call_capability() -> None:
    engine, _repository, definition = _engine()
    config = _config(TENANT_A, FIELDS_A)
    capability = _capability()
    executor = _executor(capability, tenant_tools=frozenset({"appointments.get"}))
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
    searched = await definition.search_slots(
        engine,
        executor,
        TENANT_A_CTX,
        started.workflow_id,
        command_id="search-1",
        run_id=uuid4(),
        config=config,
    )
    assert capability.operations == []
    assert searched.state == "collecting"
    assert searched.data["phase"] != "awaiting_slot_selection"
    _assert_safe_text(searched.data["error"])


@pytest.mark.anyio
async def test_mcp_target_differs_per_tenant() -> None:
    engine, _repository, definition = _engine()
    audit: list[ToolAuditEvent] = []
    capability = _capability()
    executor = _executor(capability, resolver=TenantResolver(), audit=audit)
    cases = (
        (TENANT_A_CTX, FIELDS_A, VALID_A, "a"),
        (TENANT_B_CTX, FIELDS_B, VALID_B, "b"),
    )
    for tenant, required, fields, command in cases:
        config = _config(tenant.tenant_id, required)
        started = await definition.start(
            engine, tenant, command_id=f"start-{command}", config=config
        )
        await definition.collect_fields(
            engine,
            tenant,
            started.workflow_id,
            command_id=f"collect-{command}",
            fields=fields,
            config=config,
        )
        await definition.search_slots(
            engine,
            executor,
            tenant,
            started.workflow_id,
            command_id=f"search-{command}",
            run_id=uuid4(),
            config=config,
        )
    by_tenant = {
        event.tenant_id: event.mcp_server_id for event in audit if event.allowed
    }
    assert by_tenant[TENANT_A] == "mcp-a"
    assert by_tenant[TENANT_B] == "mcp-b"


@pytest.mark.anyio
async def test_incomplete_fields_skip_executor() -> None:
    engine, _repository, definition = _engine()
    config = _config(TENANT_A, FIELDS_A)
    capability = _capability()
    executor = ExecuteSpy(_executor(capability))
    started = await definition.start(
        engine, TENANT_A_CTX, command_id="start-1", config=config
    )
    result = await definition.search_slots(
        engine,
        executor,
        TENANT_A_CTX,
        started.workflow_id,
        command_id="search-1",
        run_id=uuid4(),
        config=config,
    )
    assert executor.calls == []
    assert capability.operations == []
    assert result.data["phase"] == "collecting_fields"
    assert result.state == "collecting"


def test_t07_events_keep_engine_collecting() -> None:
    definition = CreateAppointmentDefinition()
    for event in ("collect_fields", "search_slots", "present_slots"):
        assert definition.transition("collecting", event) == "collecting"
