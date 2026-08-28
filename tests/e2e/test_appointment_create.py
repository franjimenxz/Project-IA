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
from ia_mcp.contracts.appointments import AppointmentSearchRequest, AppointmentSlot
from ia_mcp.mcp.audit import ToolAuditAdapter
from ia_mcp.mcp.executor import ToolExecutor
from ia_mcp.mcp.fakes.appointments import FakeAppointmentCapability
from ia_mcp.tenancy.models import TenantContext
from ia_mcp.workflows.adapters.sqlalchemy import SqlAlchemyWorkflowRepository
from ia_mcp.workflows.appointments.create import CreateAppointmentDefinition
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


def _config(tenant_id: UUID, required: tuple[str, ...]) -> TenantConfig:
    return TenantConfig(
        tenant_id=tenant_id,
        version=1,
        agent=AgentConfig(tone="cordial"),
        enabled_skills=frozenset({"appointments"}),
        appointments=AppointmentPolicy(required_fields=required),
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
    CreateAppointmentDefinition,
    CountingCapability,
    ToolExecutor,
    ToolAuditAdapter,
    TenantConfig,
]:
    repository = SqlAlchemyWorkflowRepository(db)
    definition = CreateAppointmentDefinition()
    engine = WorkflowEngine(repository, definition)
    capability = CountingCapability(
        clock=lambda: CLOCK,
        initial_slots={TENANT_A: (_slot(),)},
    )
    audit = ToolAuditAdapter()
    executor = ToolExecutor(
        server=ALL_TOOLS,
        tenant=ALL_TOOLS,
        skill=SEARCH_AND_CREATE,
        capability=capability,
        audit_hook=audit,
    )
    return engine, definition, capability, executor, audit, _config(TENANT_A, FIELDS_A)


async def _collect_and_select(
    engine: WorkflowEngine,
    definition: CreateAppointmentDefinition,
    executor: ToolExecutor,
    config: TenantConfig,
) -> UUID:
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
    assert searched.data["phase"] == "awaiting_slot_selection"
    selected = await definition.select_slot(
        engine,
        TENANT_A_CTX,
        started.workflow_id,
        command_id="select-1",
        slot_id="slot-a-1",
    )
    assert selected.state == "collecting"
    assert selected.data["selected_slot"] == "slot-a-1"
    _assert_no_secrets(selected.data)
    return started.workflow_id


@pytest.mark.anyio
@pytest.mark.e2e
async def test_confirm_create_replay_creates_one_appointment(db: AsyncEngine) -> None:
    engine, definition, capability, executor, audit, config = _stack(db)
    workflow_id = await _collect_and_select(engine, definition, executor, config)
    run_id = uuid4()
    first = await definition.confirm_create(
        engine,
        executor,
        TENANT_A_CTX,
        workflow_id,
        command_id="confirm-1",
        run_id=run_id,
        config=config,
        patient=PATIENT,
    )
    replay = await definition.confirm_create(
        engine,
        executor,
        TENANT_A_CTX,
        workflow_id,
        command_id="confirm-1",
        run_id=run_id,
        config=config,
        patient=PATIENT,
    )
    second_message = await definition.confirm_create(
        engine,
        executor,
        TENANT_A_CTX,
        workflow_id,
        command_id="confirm-2",
        run_id=run_id,
        config=config,
        patient=PATIENT,
    )
    assert first.state == "completed"
    assert replay.state == "completed"
    assert second_message.state == "completed"
    assert first.data["appointment_id"]
    assert replay.data["appointment_id"] == first.data["appointment_id"]
    assert second_message.data["appointment_id"] == first.data["appointment_id"]
    assert capability.operations.count("create") == 1
    _assert_no_secrets(first.data)
    _assert_no_secrets(replay.data)
    blob = repr(audit.executions)
    assert "tok-a-secret" not in blob
    assert "booking_token" not in blob


@pytest.mark.anyio
@pytest.mark.e2e
async def test_concurrent_confirms_create_one_appointment(db: AsyncEngine) -> None:
    engine, definition, capability, executor, audit, config = _stack(db)
    workflow_id = await _collect_and_select(engine, definition, executor, config)
    run_id = uuid4()
    first, second = await asyncio.gather(
        definition.confirm_create(
            engine,
            executor,
            TENANT_A_CTX,
            workflow_id,
            command_id="confirm-a",
            run_id=run_id,
            config=config,
            patient=PATIENT,
        ),
        definition.confirm_create(
            engine,
            executor,
            TENANT_A_CTX,
            workflow_id,
            command_id="confirm-b",
            run_id=run_id,
            config=config,
            patient=PATIENT,
        ),
    )
    ids = {first.data.get("appointment_id"), second.data.get("appointment_id")}
    assert len(ids) == 1
    assert ids.pop()
    assert capability.operations.count("create") == 1
    assert "completed" in {first.state, second.state}
    _assert_no_secrets(first.data)
    _assert_no_secrets(second.data)
    blob = repr(audit.executions)
    assert "tok-a-secret" not in blob
    assert "booking_token" not in blob
