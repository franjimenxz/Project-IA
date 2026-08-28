from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import command
from ia_mcp.configuration.adapters.sqlalchemy import tenant_table
from ia_mcp.tenancy.models import TenantContext
from ia_mcp.workflows.adapters.sqlalchemy import SqlAlchemyWorkflowRepository
from ia_mcp.workflows.definition import WorkflowDefinition
from ia_mcp.workflows.engine import WorkflowEngine
from ia_mcp.workflows.models import AdvanceCommand, StartWorkflow
from ia_mcp.workflows.ports import WorkflowError
from tests.fixtures.faults import (
    InjectedFault,
    instrument_workflow_repository,
    new_controller,
)
from tests.unit.workflows.fakes import InMemoryWorkflowRepository

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


@pytest.mark.anyio
@pytest.mark.integration
@pytest.mark.resilience
async def test_crash_reload_preserves_state_and_duplicate_idempotency() -> None:
    _reset_schema()
    _seed_tenants()
    first_db = create_async_engine(DATABASE_URL)
    first_repo = SqlAlchemyWorkflowRepository(first_db)
    first_engine = WorkflowEngine(first_repo, WorkflowDefinition())
    started = await first_engine.start(
        TENANT_A_CTX,
        StartWorkflow(command_id="start-1", workflow_type="generic", schema_version=1),
    )
    first = await first_engine.advance(
        TENANT_A_CTX,
        AdvanceCommand(
            workflow_id=started.workflow_id, command_id="cmd-1", event_type="submit"
        ),
    )
    await first_db.dispose()

    second_db = create_async_engine(DATABASE_URL)
    second_repo = SqlAlchemyWorkflowRepository(second_db)
    second_engine = WorkflowEngine(second_repo, WorkflowDefinition())
    try:
        loaded = await second_repo.get(TENANT_A_CTX, started.workflow_id)
        assert loaded is not None
        assert loaded.state == "awaiting_confirmation"
        assert loaded.lock_version == 2
        transitions = await second_repo.list_transitions(
            TENANT_A_CTX, started.workflow_id
        )
        assert [item.command_id for item in transitions] == ["start-1", "cmd-1"]
        assert transitions[1].to_state == "awaiting_confirmation"
        replayed = await second_engine.advance(
            TENANT_A_CTX,
            AdvanceCommand(
                workflow_id=started.workflow_id,
                command_id="cmd-1",
                event_type="submit",
            ),
        )
        assert replayed == first
        assert (
            await second_repo.count_transitions(
                TENANT_A_CTX, started.workflow_id, command_id="cmd-1"
            )
            == 1
        )
        confirmed = await second_engine.advance(
            TENANT_A_CTX,
            AdvanceCommand(
                workflow_id=started.workflow_id,
                command_id="cmd-2",
                event_type="confirm",
            ),
        )
        assert confirmed.state == "executing"
        reloaded = await second_repo.get(TENANT_A_CTX, started.workflow_id)
        assert reloaded is not None
        assert reloaded.state == "executing"
    finally:
        await second_db.dispose()


@pytest.mark.anyio
@pytest.mark.resilience
async def test_in_memory_crash_before_cas_retries_once() -> None:
    inner = InMemoryWorkflowRepository()
    controller = new_controller(
        InjectedFault(dependency="db", boundary="before", kind="unavailable")
    )
    engine = WorkflowEngine(
        instrument_workflow_repository(inner, controller), WorkflowDefinition()
    )
    started = await engine.start(
        TENANT_A_CTX,
        StartWorkflow(command_id="start-1", workflow_type="generic", schema_version=1),
    )
    with pytest.raises(WorkflowError):
        await engine.advance(
            TENANT_A_CTX,
            AdvanceCommand(
                workflow_id=started.workflow_id,
                command_id="cmd-1",
                event_type="submit",
            ),
        )
    recovered = await engine.advance(
        TENANT_A_CTX,
        AdvanceCommand(
            workflow_id=started.workflow_id,
            command_id="cmd-1",
            event_type="submit",
        ),
    )
    assert recovered.state == "awaiting_confirmation"
    assert controller.side_effect_count("db.cas_advance") == 1
    assert (
        await inner.count_transitions(
            TENANT_A_CTX, started.workflow_id, command_id="cmd-1"
        )
        == 1
    )


@pytest.mark.anyio
@pytest.mark.resilience
async def test_in_memory_crash_after_cas_replays_recorded_transition() -> None:
    inner = InMemoryWorkflowRepository()
    controller = new_controller(
        InjectedFault(dependency="db", boundary="after", kind="unavailable")
    )
    engine = WorkflowEngine(
        instrument_workflow_repository(inner, controller), WorkflowDefinition()
    )
    started = await engine.start(
        TENANT_A_CTX,
        StartWorkflow(command_id="start-1", workflow_type="generic", schema_version=1),
    )
    with pytest.raises(WorkflowError):
        await engine.advance(
            TENANT_A_CTX,
            AdvanceCommand(
                workflow_id=started.workflow_id,
                command_id="cmd-1",
                event_type="submit",
            ),
        )
    assert controller.side_effect_count("db.cas_advance") == 1
    recovered = await engine.advance(
        TENANT_A_CTX,
        AdvanceCommand(
            workflow_id=started.workflow_id,
            command_id="cmd-1",
            event_type="submit",
        ),
    )
    assert recovered.state == "awaiting_confirmation"
    assert (
        await inner.count_transitions(
            TENANT_A_CTX, started.workflow_id, command_id="cmd-1"
        )
        == 1
    )
