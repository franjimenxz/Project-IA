from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from alembic import command
from ia_mcp.configuration.adapters.sqlalchemy import tenant_table
from ia_mcp.tenancy.models import TenantContext
from ia_mcp.workflows.adapters.sqlalchemy import (
    SqlAlchemyWorkflowRepository,
    outbox_event_table,
    workflow_execution_table,
    workflow_transition_table,
)
from ia_mcp.workflows.definition import WorkflowDefinition
from ia_mcp.workflows.engine import WorkflowEngine
from ia_mcp.workflows.models import (
    AdvanceCommand,
    OutboxEvent,
    StartWorkflow,
    WorkflowTransition,
)
from ia_mcp.workflows.ports import WorkflowError

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


@dataclass(slots=True)
class Harness:
    engine: WorkflowEngine
    repository: SqlAlchemyWorkflowRepository
    db: AsyncEngine
    workflow_id: UUID


@pytest.fixture
async def harness() -> AsyncIterator[Harness]:
    _reset_schema()
    _seed_tenants()
    db = create_async_engine(DATABASE_URL)
    repository = SqlAlchemyWorkflowRepository(db)
    engine = WorkflowEngine(repository, WorkflowDefinition())
    started = await engine.start(
        TENANT_A_CTX,
        StartWorkflow(command_id="start-1", workflow_type="generic", schema_version=1),
    )
    try:
        yield Harness(engine, repository, db, started.workflow_id)
    finally:
        await db.dispose()


def _command(
    workflow_id: UUID, *, id: str, event_type: str = "submit"
) -> AdvanceCommand:
    return AdvanceCommand(
        workflow_id=workflow_id, command_id=id, event_type=event_type
    )


@pytest.mark.anyio
@pytest.mark.integration
async def test_duplicate_command_returns_recorded_transition(harness: Harness) -> None:
    first = await harness.engine.advance(
        TENANT_A_CTX, _command(harness.workflow_id, id="cmd-1")
    )
    second = await harness.engine.advance(
        TENANT_A_CTX, _command(harness.workflow_id, id="cmd-1")
    )
    assert second == first
    assert (
        await harness.repository.count_transitions(
            TENANT_A_CTX, harness.workflow_id, command_id="cmd-1"
        )
        == 1
    )


@pytest.mark.anyio
@pytest.mark.integration
async def test_concurrent_advance_cas_conflict(harness: Harness) -> None:
    results = await asyncio.gather(
        harness.engine.advance(
            TENANT_A_CTX, _command(harness.workflow_id, id="cmd-a")
        ),
        harness.engine.advance(
            TENANT_A_CTX, _command(harness.workflow_id, id="cmd-b")
        ),
        return_exceptions=True,
    )
    successes = [item for item in results if not isinstance(item, BaseException)]
    failures = [item for item in results if isinstance(item, WorkflowError)]
    assert len(successes) == 1
    assert len(failures) == 1
    assert failures[0].code in {"conflict", "invalid_transition"}
    loaded = await harness.repository.get(TENANT_A_CTX, harness.workflow_id)
    assert loaded is not None
    assert loaded.state == "awaiting_confirmation"
    assert loaded.lock_version == 2
    total = await harness.repository.count_transitions(
        TENANT_A_CTX, harness.workflow_id
    )
    assert total == 2


@pytest.mark.anyio
@pytest.mark.integration
async def test_invalid_transition_fails_closed_without_mutating(
    harness: Harness,
) -> None:
    with pytest.raises(WorkflowError) as caught:
        await harness.engine.advance(
            TENANT_A_CTX,
            _command(harness.workflow_id, id="bad-1", event_type="confirm"),
        )
    assert caught.value.code == "invalid_transition"
    loaded = await harness.repository.get(TENANT_A_CTX, harness.workflow_id)
    assert loaded is not None
    assert loaded.state == "collecting"
    assert loaded.lock_version == 1
    assert (
        await harness.repository.count_transitions(
            TENANT_A_CTX, harness.workflow_id, command_id="bad-1"
        )
        == 0
    )
    async with harness.db.connect() as connection:
        outbox_count = await connection.scalar(
            select(func.count())
            .select_from(outbox_event_table)
            .where(outbox_event_table.c.tenant_id == TENANT_A)
        )
    assert outbox_count == 1


@pytest.mark.anyio
@pytest.mark.integration
async def test_tenant_b_cannot_read_or_advance_tenant_a(harness: Harness) -> None:
    with pytest.raises(WorkflowError) as caught:
        await harness.engine.advance(
            TENANT_B_CTX, _command(harness.workflow_id, id="cmd-x")
        )
    assert caught.value.code == "not_found"
    assert "Resource not found" == caught.value.safe_message
    assert str(harness.workflow_id) not in caught.value.safe_message
    assert await harness.repository.get(TENANT_B_CTX, harness.workflow_id) is None
    assert (
        await harness.repository.list_transitions(TENANT_B_CTX, harness.workflow_id)
        == ()
    )
    loaded = await harness.repository.get(TENANT_A_CTX, harness.workflow_id)
    assert loaded is not None
    assert loaded.state == "collecting"


@pytest.mark.anyio
@pytest.mark.integration
async def test_outbox_written_in_same_transaction_as_transition(
    harness: Harness,
) -> None:
    result = await harness.engine.advance(
        TENANT_A_CTX,
        AdvanceCommand(
            workflow_id=harness.workflow_id,
            command_id="cmd-1",
            event_type="submit",
            payload={"note": "ok", "password": "supersecret"},
        ),
    )
    assert result.state == "awaiting_confirmation"
    async with harness.db.connect() as connection:
        transitions = (
            (
                await connection.execute(
                    select(workflow_transition_table).where(
                        workflow_transition_table.c.tenant_id == TENANT_A,
                        workflow_transition_table.c.command_id == "cmd-1",
                    )
                )
            )
            .mappings()
            .all()
        )
        outbox_rows = (
            (
                await connection.execute(
                    select(outbox_event_table).where(
                        outbox_event_table.c.tenant_id == TENANT_A,
                        outbox_event_table.c.kind == "workflow.transitioned",
                    )
                )
            )
            .mappings()
            .all()
        )
        executions = (
            (
                await connection.execute(
                    select(workflow_execution_table).where(
                        workflow_execution_table.c.tenant_id == TENANT_A,
                        workflow_execution_table.c.id == harness.workflow_id,
                    )
                )
            )
            .mappings()
            .all()
        )
    assert len(transitions) == 1
    assert len(outbox_rows) == 1
    assert len(executions) == 1
    dumped = str(transitions[0]["payload"]) + str(outbox_rows[0]["payload"])
    assert "supersecret" not in dumped
    assert "password" not in dumped
    assert transitions[0]["payload"]["note"] == "ok"


@pytest.mark.anyio
@pytest.mark.integration
async def test_concurrent_cas_update_conflicts_on_lock_version(harness: Harness) -> None:
    loaded = await harness.repository.get(TENANT_A_CTX, harness.workflow_id)
    assert loaded is not None
    now = datetime.now(UTC)

    async def attempt(command_id: str) -> object:
        updated = replace(
            loaded,
            state="awaiting_confirmation",
            status="running",
            lock_version=2,
            updated_at=now,
        )
        transition = WorkflowTransition(
            tenant_id=TENANT_A,
            workflow_id=harness.workflow_id,
            sequence=2,
            from_state="collecting",
            to_state="awaiting_confirmation",
            command_id=command_id,
            event_type="submit",
            payload={},
            actor="system",
            run_id=None,
            timestamp=now,
        )
        outbox = OutboxEvent(
            tenant_id=TENANT_A,
            id=uuid4(),
            kind="workflow.transitioned",
            payload={"command_id": command_id},
            created_at=now,
        )
        return await harness.repository.cas_advance(
            TENANT_A_CTX, 1, updated, transition, outbox
        )

    results = await asyncio.gather(
        attempt("cmd-cas-a"), attempt("cmd-cas-b"), return_exceptions=True
    )
    successes = [item for item in results if not isinstance(item, BaseException)]
    conflicts = [
        item
        for item in results
        if isinstance(item, WorkflowError) and item.code == "conflict"
    ]
    assert len(successes) == 1
    assert len(conflicts) == 1
    loaded = await harness.repository.get(TENANT_A_CTX, harness.workflow_id)
    assert loaded is not None
    assert loaded.lock_version == 2
    assert loaded.state == "awaiting_confirmation"
    assert await harness.repository.count_transitions(
        TENANT_A_CTX, harness.workflow_id
    ) == 2


@pytest.mark.integration
def test_workflows_migration_up_and_down() -> None:
    _reset_schema()
    alembic_cfg = Config(str(ROOT / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(ROOT / "alembic"))
    alembic_cfg.set_main_option("sqlalchemy.url", DATABASE_URL)
    engine = create_engine(DATABASE_URL)
    with engine.connect() as connection:
        tables = set(
            connection.execute(
                text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
            )
            .scalars()
            .all()
        )
    engine.dispose()
    assert {
        "workflow_execution",
        "workflow_transition",
        "outbox_event",
        "knowledge_document",
        "tenant",
    } <= tables
    command.downgrade(alembic_cfg, "0003_knowledge")
    engine = create_engine(DATABASE_URL)
    with engine.connect() as connection:
        tables = set(
            connection.execute(
                text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
            )
            .scalars()
            .all()
        )
    engine.dispose()
    assert "workflow_execution" not in tables
    assert "workflow_transition" not in tables
    assert "outbox_event" not in tables
    assert "knowledge_document" in tables
    assert "tenant" in tables
    command.upgrade(alembic_cfg, "head")
