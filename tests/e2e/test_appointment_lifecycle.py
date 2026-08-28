from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from alembic.config import Config
from pydantic import SecretStr
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from alembic import command
from ia_mcp.configuration.adapters.sqlalchemy import tenant_table
from ia_mcp.contracts.appointments import (
    AppointmentCreateRequest,
    AppointmentGetRequest,
    AppointmentSlot,
    AppointmentStatus,
    PatientRef,
)
from ia_mcp.mcp.audit import ToolAuditAdapter
from ia_mcp.mcp.executor import ToolExecutor
from ia_mcp.mcp.fakes.appointments import FakeAppointmentCapability
from ia_mcp.tenancy.models import TenantContext
from ia_mcp.workflows.adapters.sqlalchemy import SqlAlchemyWorkflowRepository
from ia_mcp.workflows.appointments.confirm import ConfirmAppointmentDefinition
from ia_mcp.workflows.appointments.reschedule import RescheduleAppointmentDefinition
from ia_mcp.workflows.engine import WorkflowEngine

ROOT = Path(__file__).resolve().parents[2]
DATABASE_URL = "postgresql+psycopg://francojimenez@127.0.0.1:5432/ia_mcp_p02_t03"

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


def _reset_schema() -> None:
    engine = create_engine(DATABASE_URL)
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))
    engine.dispose()
    alembic_cfg = Config(str(ROOT / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(ROOT / "alembic"))
    alembic_cfg.set_main_option("sqlalchemy.url", DATABASE_URL)
    command.upgrade(alembic_cfg, "head")


def _seed_tenants() -> None:
    engine = create_engine(DATABASE_URL)
    now = datetime.now(UTC)
    with engine.begin() as connection:
        connection.execute(
            tenant_table.insert(),
            [
                {
                    "id": TENANT_A,
                    "slug": "tenant-a",
                    "status": "active",
                    "active_config_version": None,
                    "created_at": now,
                    "updated_at": now,
                },
                {
                    "id": TENANT_B,
                    "slug": "tenant-b",
                    "status": "active",
                    "active_config_version": None,
                    "created_at": now,
                    "updated_at": now,
                },
            ],
        )
    engine.dispose()


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


@pytest.fixture
async def db() -> AsyncIterator[AsyncEngine]:
    _reset_schema()
    _seed_tenants()
    engine = create_async_engine(DATABASE_URL)
    try:
        yield engine
    finally:
        await engine.dispose()


def _capability() -> CountingCapability:
    return CountingCapability(
        clock=lambda: CLOCK,
        initial_slots={
            TENANT_A: (
                _slot("slot-a-1", 13, token="tok-a-secret"),
                _slot("slot-a-2", 14, token="tok-a2-secret"),
            ),
            TENANT_B: (_slot("slot-b-1", 13, token="tok-b-secret"),),
        },
    )


def _reschedule_stack(
    db: AsyncEngine, capability: CountingCapability
) -> tuple[WorkflowEngine, RescheduleAppointmentDefinition, ToolExecutor, ToolAuditAdapter]:
    repository = SqlAlchemyWorkflowRepository(db)
    definition = RescheduleAppointmentDefinition()
    engine = WorkflowEngine(repository, definition)
    audit = ToolAuditAdapter()
    executor = ToolExecutor(
        server=ALL_TOOLS,
        tenant=ALL_TOOLS,
        skill=RESCHEDULE_TOOLS,
        capability=capability,
        audit_hook=audit,
    )
    return engine, definition, executor, audit


def _confirm_stack(
    db: AsyncEngine, capability: CountingCapability
) -> tuple[WorkflowEngine, ConfirmAppointmentDefinition, ToolExecutor, ToolAuditAdapter]:
    repository = SqlAlchemyWorkflowRepository(db)
    definition = ConfirmAppointmentDefinition()
    engine = WorkflowEngine(repository, definition)
    audit = ToolAuditAdapter()
    executor = ToolExecutor(
        server=ALL_TOOLS,
        tenant=ALL_TOOLS,
        skill=CONFIRM_TOOLS,
        capability=capability,
        audit_hook=audit,
    )
    return engine, definition, executor, audit


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
    searched = await definition.search_slots(
        engine,
        executor,
        TENANT_A_CTX,
        started.workflow_id,
        command_id="search-1",
        run_id=uuid4(),
    )
    assert searched.data["phase"] == "awaiting_slot_selection"
    _assert_no_secrets(searched.data)
    await definition.select_slot(
        engine,
        TENANT_A_CTX,
        started.workflow_id,
        command_id="select-1",
        slot_id="slot-a-2",
    )
    return started.workflow_id


@pytest.mark.anyio
@pytest.mark.e2e
async def test_reschedule_replay_mutates_once(db: AsyncEngine) -> None:
    capability = _capability()
    engine, definition, executor, audit = _reschedule_stack(db, capability)
    original_id = await _seed(capability, TENANT_A_CTX, "slot-a-1", "seed-1")
    workflow_id = await _prepare_reschedule(engine, definition, executor, original_id)
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
    assert "cancel" not in capability.operations
    _assert_no_secrets(first.data)
    blob = repr(audit.executions)
    assert "tok-a-secret" not in blob
    assert "booking_token" not in blob


@pytest.mark.anyio
@pytest.mark.e2e
async def test_lost_slot_keeps_original_appointment(db: AsyncEngine) -> None:
    capability = _capability()
    engine, definition, executor, _audit = _reschedule_stack(db, capability)
    original_id = await _seed(capability, TENANT_A_CTX, "slot-a-1", "seed-1")
    workflow_id = await _prepare_reschedule(engine, definition, executor, original_id)
    await _seed(capability, TENANT_A_CTX, "slot-a-2", "occupy-a-2")
    result = await definition.confirm_reschedule(
        engine,
        executor,
        TENANT_A_CTX,
        workflow_id,
        command_id="confirm-1",
        run_id=uuid4(),
    )
    assert result.state != "completed"
    assert result.data.get("phase") == "awaiting_slot_selection"
    assert capability.operations.count("reschedule") == 0
    got = await capability.get(
        TENANT_A_CTX, AppointmentGetRequest(appointment_id=original_id)
    )
    assert got.ok
    assert got.value is not None
    assert got.value.status is AppointmentStatus.SCHEDULED
    _assert_no_secrets(result.data)


@pytest.mark.anyio
@pytest.mark.e2e
async def test_confirm_replay_confirms_once(db: AsyncEngine) -> None:
    capability = _capability()
    engine, definition, executor, audit = _confirm_stack(db, capability)
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
    first = await definition.confirm_appointment(
        engine,
        executor,
        TENANT_A_CTX,
        started.workflow_id,
        command_id="confirm-1",
        run_id=uuid4(),
    )
    replay = await definition.confirm_appointment(
        engine,
        executor,
        TENANT_A_CTX,
        started.workflow_id,
        command_id="confirm-1",
        run_id=uuid4(),
    )
    assert first.state == "completed"
    assert replay.state == "completed"
    assert capability.operations.count("confirm") == 1
    _assert_no_secrets(first.data)
    blob = repr(audit.executions)
    assert "tok-a-secret" not in blob
    assert "booking_token" not in blob


@pytest.mark.anyio
@pytest.mark.e2e
async def test_tenant_a_cannot_mutate_tenant_b_appointment(db: AsyncEngine) -> None:
    capability = _capability()
    confirm_engine, confirm_def, confirm_exec, _audit = _confirm_stack(db, capability)
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
    await confirm_def.confirm_appointment(
        confirm_engine,
        confirm_exec,
        TENANT_A_CTX,
        started.workflow_id,
        command_id="confirm-1",
        run_id=uuid4(),
    )
    reschedule_engine, reschedule_def, reschedule_exec, _a2 = _reschedule_stack(
        db, capability
    )
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


@pytest.mark.anyio
@pytest.mark.e2e
async def test_concurrent_reschedule_mutates_once(db: AsyncEngine) -> None:
    capability = _capability()
    engine, definition, executor, _audit = _reschedule_stack(db, capability)
    original_id = await _seed(capability, TENANT_A_CTX, "slot-a-1", "seed-1")
    workflow_id = await _prepare_reschedule(engine, definition, executor, original_id)
    run_id = uuid4()
    first, second = await asyncio.gather(
        definition.confirm_reschedule(
            engine,
            executor,
            TENANT_A_CTX,
            workflow_id,
            command_id="confirm-a",
            run_id=run_id,
        ),
        definition.confirm_reschedule(
            engine,
            executor,
            TENANT_A_CTX,
            workflow_id,
            command_id="confirm-b",
            run_id=run_id,
        ),
    )
    assert "completed" in {first.state, second.state}
    assert capability.operations.count("reschedule") == 1
    _assert_no_secrets(first.data)
    _assert_no_secrets(second.data)
