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
from ia_mcp.configuration.models import AgentConfig, AppointmentPolicy, TenantConfig
from ia_mcp.contracts.appointments import (
    AppointmentCancelRequest,
    AppointmentCreateRequest,
    AppointmentSlot,
    AppointmentStatus,
    PatientRef,
)
from ia_mcp.mcp.audit import ToolAuditAdapter
from ia_mcp.mcp.executor import ToolExecutor
from ia_mcp.mcp.fakes.appointments import FakeAppointmentCapability
from ia_mcp.tenancy.models import TenantContext
from ia_mcp.workflows.adapters.sqlalchemy import SqlAlchemyWorkflowRepository
from ia_mcp.workflows.appointments.cancel import CancelAppointmentDefinition
from ia_mcp.workflows.engine import WorkflowEngine
from tests.fixtures.database import DATABASE_URL

ROOT = Path(__file__).resolve().parents[2]

TENANT_A = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
TENANT_B = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
TENANT_A_CTX = TenantContext(
    tenant_id=TENANT_A,
    tenant_slug="tenant-a",
    config_version=1,
    correlation_id=UUID("33333333-3333-3333-3333-333333333333"),
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


def _config(tenant_id: UUID) -> TenantConfig:
    return TenantConfig(
        tenant_id=tenant_id,
        version=1,
        agent=AgentConfig(tone="cordial"),
        enabled_skills=frozenset({"appointments"}),
        appointments=AppointmentPolicy(),
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

    async def get(self, tenant: TenantContext, request: Any):
        self.operations.append("get")
        return await super().get(tenant, request)

    async def create(self, tenant: TenantContext, request: Any, idempotency_key: str):
        self.operations.append("create")
        return await super().create(tenant, request, idempotency_key)

    async def cancel(self, tenant: TenantContext, request: Any, idempotency_key: str):
        self.operations.append("cancel")
        return await super().cancel(tenant, request, idempotency_key)


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


def _stack(db: AsyncEngine) -> tuple[
    WorkflowEngine,
    CancelAppointmentDefinition,
    CountingCapability,
    ToolExecutor,
    ToolAuditAdapter,
    TenantConfig,
]:
    repository = SqlAlchemyWorkflowRepository(db)
    definition = CancelAppointmentDefinition()
    engine = WorkflowEngine(repository, definition)
    capability = CountingCapability(
        clock=lambda: CLOCK,
        id_factory=lambda: "appt-a-1",
        initial_slots={TENANT_A: (_slot(),)},
    )
    audit = ToolAuditAdapter()
    executor = ToolExecutor(
        server=ALL_TOOLS,
        tenant=ALL_TOOLS,
        skill=GET_AND_CANCEL,
        capability=capability,
        audit_hook=audit,
    )
    return engine, definition, capability, executor, audit, _config(TENANT_A)


async def _seed(capability: CountingCapability) -> str:
    result = await capability.create(
        TENANT_A_CTX,
        AppointmentCreateRequest(
            slot_id="slot-a-1",
            booking_token=SecretStr("tok-a-secret"),
            patient=PATIENT,
        ),
        idempotency_key="seed-create-a",
    )
    assert result.ok
    assert result.value is not None
    return result.value.appointment_id


async def _lookup(
    engine: WorkflowEngine,
    definition: CancelAppointmentDefinition,
    executor: ToolExecutor,
    config: TenantConfig,
    appointment_id: str,
) -> UUID:
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
    _assert_no_secrets(looked.data)
    return started.workflow_id


@pytest.mark.anyio
@pytest.mark.e2e
async def test_confirm_cancel_replay_cancels_once(db: AsyncEngine) -> None:
    engine, definition, capability, executor, audit, config = _stack(db)
    appointment_id = await _seed(capability)
    capability.operations.clear()
    workflow_id = await _lookup(engine, definition, executor, config, appointment_id)
    run_id = uuid4()
    first = await definition.confirm_cancel(
        engine,
        executor,
        TENANT_A_CTX,
        workflow_id,
        command_id="confirm-1",
        run_id=run_id,
        config=config,
        confirmed=True,
    )
    replay = await definition.confirm_cancel(
        engine,
        executor,
        TENANT_A_CTX,
        workflow_id,
        command_id="confirm-1",
        run_id=run_id,
        config=config,
        confirmed=True,
    )
    second = await definition.confirm_cancel(
        engine,
        executor,
        TENANT_A_CTX,
        workflow_id,
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
    _assert_no_secrets(first.data)
    _assert_no_secrets(replay.data)
    blob = repr(audit.executions)
    assert "tok-a-secret" not in blob
    assert "booking_token" not in blob


@pytest.mark.anyio
@pytest.mark.e2e
async def test_concurrent_confirms_cancel_one_appointment(db: AsyncEngine) -> None:
    engine, definition, capability, executor, audit, config = _stack(db)
    appointment_id = await _seed(capability)
    capability.operations.clear()
    workflow_id = await _lookup(engine, definition, executor, config, appointment_id)
    run_id = uuid4()
    first, second = await asyncio.gather(
        definition.confirm_cancel(
            engine,
            executor,
            TENANT_A_CTX,
            workflow_id,
            command_id="confirm-a",
            run_id=run_id,
            config=config,
            confirmed=True,
        ),
        definition.confirm_cancel(
            engine,
            executor,
            TENANT_A_CTX,
            workflow_id,
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
    _assert_no_secrets(first.data)
    _assert_no_secrets(second.data)
    blob = repr(audit.executions)
    assert "tok-a-secret" not in blob
    assert "booking_token" not in blob


@pytest.mark.anyio
@pytest.mark.e2e
async def test_already_cancelled_completes_without_error(db: AsyncEngine) -> None:
    engine, definition, capability, executor, audit, config = _stack(db)
    appointment_id = await _seed(capability)
    pre = await capability.cancel(
        TENANT_A_CTX,
        AppointmentCancelRequest(appointment_id=appointment_id),
        idempotency_key="pre-cancel",
    )
    assert pre.ok
    capability.operations.clear()
    workflow_id = await _lookup(engine, definition, executor, config, appointment_id)
    confirmed = await definition.confirm_cancel(
        engine,
        executor,
        TENANT_A_CTX,
        workflow_id,
        command_id="confirm-1",
        run_id=uuid4(),
        config=config,
        confirmed=True,
    )
    assert confirmed.state == "completed"
    assert confirmed.error is None
    assert capability.operations.count("cancel") <= 1
    assert (
        capability._agenda(TENANT_A_CTX).appointments[appointment_id].status
        is AppointmentStatus.CANCELLED
    )
    _assert_no_secrets(confirmed.data)
    blob = repr(audit.executions)
    assert "tok-a-secret" not in blob
    assert "booking_token" not in blob
