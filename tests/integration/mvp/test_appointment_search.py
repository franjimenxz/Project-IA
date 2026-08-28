from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic.config import Config
from pydantic import SecretStr
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from alembic import command
from ia_mcp.configuration.adapters.sqlalchemy import tenant_table
from ia_mcp.configuration.models import AgentConfig, AppointmentPolicy, TenantConfig
from ia_mcp.contracts.appointments import AppointmentSlot
from ia_mcp.mcp.executor import ToolExecutor
from ia_mcp.mcp.fakes.appointments import FakeAppointmentCapability
from ia_mcp.tenancy.models import TenantContext
from ia_mcp.workflows.adapters.sqlalchemy import SqlAlchemyWorkflowRepository
from ia_mcp.workflows.appointments.create import CreateAppointmentDefinition
from ia_mcp.workflows.engine import WorkflowEngine

ROOT = Path(__file__).resolve().parents[3]
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


@pytest.fixture
async def db() -> AsyncIterator[AsyncEngine]:
    _reset_schema()
    _seed_tenants()
    engine = create_async_engine(DATABASE_URL)
    try:
        yield engine
    finally:
        await engine.dispose()


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
@pytest.mark.integration
async def test_start_collect_search_persists_and_reloads(db: AsyncEngine) -> None:
    repository = SqlAlchemyWorkflowRepository(db)
    definition = CreateAppointmentDefinition()
    engine = WorkflowEngine(repository, definition)
    capability = FakeAppointmentCapability(
        clock=lambda: CLOCK,
        initial_slots={TENANT_A: (_slot(),), TENANT_B: (_slot(),)},
    )
    executor = ToolExecutor(
        server=ALL_TOOLS,
        tenant=ALL_TOOLS,
        skill=frozenset({"appointments.search"}),
        capability=capability,
    )
    config_a = _config(TENANT_A, FIELDS_A)
    started_a = await definition.start(
        engine, TENANT_A_CTX, command_id="start-a", config=config_a
    )
    await definition.collect_fields(
        engine,
        TENANT_A_CTX,
        started_a.workflow_id,
        command_id="collect-a",
        fields=VALID_A,
        config=config_a,
    )
    searched_a = await definition.search_slots(
        engine,
        executor,
        TENANT_A_CTX,
        started_a.workflow_id,
        command_id="search-a",
        run_id=uuid4(),
        config=config_a,
    )
    assert searched_a.state == "collecting"
    assert searched_a.data["phase"] == "awaiting_slot_selection"
    _assert_no_secrets(searched_a.data)

    config_b = _config(TENANT_B, FIELDS_B)
    started_b = await definition.start(
        engine, TENANT_B_CTX, command_id="start-b", config=config_b
    )
    incomplete_b = await definition.collect_fields(
        engine,
        TENANT_B_CTX,
        started_b.workflow_id,
        command_id="collect-b-bad",
        fields=VALID_A,
        config=config_b,
    )
    assert incomplete_b.data["phase"] == "collecting_fields"
    await definition.collect_fields(
        engine,
        TENANT_B_CTX,
        started_b.workflow_id,
        command_id="collect-b",
        fields=VALID_B,
        config=config_b,
    )
    searched_b = await definition.search_slots(
        engine,
        executor,
        TENANT_B_CTX,
        started_b.workflow_id,
        command_id="search-b",
        run_id=uuid4(),
        config=config_b,
    )
    assert searched_b.data["phase"] == "awaiting_slot_selection"

    reloaded_db = create_async_engine(DATABASE_URL)
    try:
        reloaded_repo = SqlAlchemyWorkflowRepository(reloaded_db)
        loaded_a = await reloaded_repo.get(TENANT_A_CTX, started_a.workflow_id)
        loaded_b = await reloaded_repo.get(TENANT_B_CTX, started_b.workflow_id)
    finally:
        await reloaded_db.dispose()
    assert loaded_a is not None
    assert loaded_a.type == "create_appointment"
    assert loaded_a.state == "collecting"
    assert loaded_a.data["phase"] == "awaiting_slot_selection"
    _assert_no_secrets(dict(loaded_a.data))
    assert loaded_b is not None
    assert loaded_b.type == "create_appointment"
    assert loaded_b.state == "collecting"
    assert loaded_b.data["phase"] == "awaiting_slot_selection"
    assert loaded_a.data.get("practitioner") is None
    assert loaded_b.data.get("practitioner") == "Dr. Ada"
