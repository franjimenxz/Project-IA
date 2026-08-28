from typing import Any, cast
from uuid import UUID

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKeyConstraint,
    Integer,
    MetaData,
    PrimaryKeyConstraint,
    String,
    Table,
    UniqueConstraint,
    func,
    select,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from ia_mcp.tenancy.models import TenantContext
from ia_mcp.workflows.models import (
    OutboxEvent,
    WorkflowExecution,
    WorkflowState,
    WorkflowStatus,
    WorkflowTransition,
)
from ia_mcp.workflows.ports import WorkflowError

metadata = MetaData()

workflow_execution_table = Table(
    "workflow_execution",
    metadata,
    Column("tenant_id", PGUUID(as_uuid=True), nullable=False),
    Column("id", PGUUID(as_uuid=True), nullable=False),
    Column("conversation_id", PGUUID(as_uuid=True), nullable=True),
    Column("type", String(64), nullable=False),
    Column("schema_version", Integer, nullable=False),
    Column("state", String(64), nullable=False),
    Column("status", String(32), nullable=False),
    Column("data", JSONB, nullable=False),
    Column("idempotency_key_hash", String(64), nullable=True),
    Column("lock_version", Integer, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    Column("error", String(128), nullable=True),
    PrimaryKeyConstraint("tenant_id", "id"),
    UniqueConstraint("tenant_id", "id"),
    UniqueConstraint(
        "tenant_id",
        "idempotency_key_hash",
        name="uq_workflow_execution_idempotency",
    ),
)

workflow_transition_table = Table(
    "workflow_transition",
    metadata,
    Column("tenant_id", PGUUID(as_uuid=True), nullable=False),
    Column("workflow_id", PGUUID(as_uuid=True), nullable=False),
    Column("sequence", Integer, nullable=False),
    Column("from_state", String(64), nullable=True),
    Column("to_state", String(64), nullable=False),
    Column("command_id", String(128), nullable=False),
    Column("event_type", String(64), nullable=False),
    Column("payload", JSONB, nullable=False),
    Column("actor", String(64), nullable=False),
    Column("run_id", PGUUID(as_uuid=True), nullable=True),
    Column("timestamp", DateTime(timezone=True), nullable=False),
    PrimaryKeyConstraint("tenant_id", "workflow_id", "sequence"),
    UniqueConstraint(
        "tenant_id",
        "workflow_id",
        "command_id",
        name="uq_workflow_transition_command",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "workflow_id"],
        ["workflow_execution.tenant_id", "workflow_execution.id"],
    ),
)

outbox_event_table = Table(
    "outbox_event",
    metadata,
    Column("tenant_id", PGUUID(as_uuid=True), nullable=False),
    Column("id", PGUUID(as_uuid=True), nullable=False),
    Column("kind", String(64), nullable=False),
    Column("payload", JSONB, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    PrimaryKeyConstraint("tenant_id", "id"),
)


def _state(value: object) -> WorkflowState:
    return cast(WorkflowState, value)


def _status(value: object) -> WorkflowStatus:
    return cast(WorkflowStatus, value)


def _payload(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    return {str(key): item for key, item in value.items()}


def _execution_from_row(row: Any) -> WorkflowExecution:
    return WorkflowExecution(
        tenant_id=row["tenant_id"],
        id=row["id"],
        conversation_id=row["conversation_id"],
        type=row["type"],
        schema_version=int(row["schema_version"]),
        state=_state(row["state"]),
        status=_status(row["status"]),
        data=_payload(row["data"]),
        idempotency_key_hash=row["idempotency_key_hash"],
        lock_version=int(row["lock_version"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        error=row["error"],
    )


def _transition_from_row(row: Any) -> WorkflowTransition:
    raw_from = row["from_state"]
    return WorkflowTransition(
        tenant_id=row["tenant_id"],
        workflow_id=row["workflow_id"],
        sequence=int(row["sequence"]),
        from_state=_state(raw_from) if raw_from is not None else None,
        to_state=_state(row["to_state"]),
        command_id=row["command_id"],
        event_type=row["event_type"],
        payload=_payload(row["payload"]),
        actor=row["actor"],
        run_id=row["run_id"],
        timestamp=row["timestamp"],
    )


def _execution_values(execution: WorkflowExecution) -> dict[str, object]:
    return {
        "tenant_id": execution.tenant_id,
        "id": execution.id,
        "conversation_id": execution.conversation_id,
        "type": execution.type,
        "schema_version": execution.schema_version,
        "state": execution.state,
        "status": execution.status,
        "data": dict(execution.data),
        "idempotency_key_hash": execution.idempotency_key_hash,
        "lock_version": execution.lock_version,
        "created_at": execution.created_at,
        "updated_at": execution.updated_at,
        "error": execution.error,
    }


def _transition_values(transition: WorkflowTransition) -> dict[str, object]:
    return {
        "tenant_id": transition.tenant_id,
        "workflow_id": transition.workflow_id,
        "sequence": transition.sequence,
        "from_state": transition.from_state,
        "to_state": transition.to_state,
        "command_id": transition.command_id,
        "event_type": transition.event_type,
        "payload": dict(transition.payload),
        "actor": transition.actor,
        "run_id": transition.run_id,
        "timestamp": transition.timestamp,
    }


def _outbox_values(outbox: OutboxEvent) -> dict[str, object]:
    return {
        "tenant_id": outbox.tenant_id,
        "id": outbox.id,
        "kind": outbox.kind,
        "payload": dict(outbox.payload),
        "created_at": outbox.created_at,
    }


class SqlAlchemyWorkflowRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self._session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def create(
        self,
        tenant: TenantContext,
        execution: WorkflowExecution,
        transition: WorkflowTransition,
        outbox: OutboxEvent,
    ) -> None:
        if execution.tenant_id != tenant.tenant_id:
            raise WorkflowError("not_found", "Resource not found")
        try:
            async with self._session_factory() as session, session.begin():
                await session.execute(
                    workflow_execution_table.insert().values(
                        **_execution_values(execution)
                    )
                )
                await session.execute(
                    workflow_transition_table.insert().values(
                        **_transition_values(transition)
                    )
                )
                await session.execute(
                    outbox_event_table.insert().values(**_outbox_values(outbox))
                )
        except IntegrityError as exc:
            raise WorkflowError(
                "conflict", "Workflow was updated concurrently."
            ) from exc

    async def get(
        self, tenant: TenantContext, workflow_id: UUID
    ) -> WorkflowExecution | None:
        async with self._session_factory() as session:
            row = (
                (
                    await session.execute(
                        select(workflow_execution_table).where(
                            workflow_execution_table.c.tenant_id == tenant.tenant_id,
                            workflow_execution_table.c.id == workflow_id,
                        )
                    )
                )
                .mappings()
                .first()
            )
            if row is None:
                return None
            return _execution_from_row(row)

    async def get_by_idempotency(
        self, tenant: TenantContext, idempotency_key_hash: str
    ) -> WorkflowExecution | None:
        async with self._session_factory() as session:
            row = (
                (
                    await session.execute(
                        select(workflow_execution_table).where(
                            workflow_execution_table.c.tenant_id == tenant.tenant_id,
                            workflow_execution_table.c.idempotency_key_hash
                            == idempotency_key_hash,
                        )
                    )
                )
                .mappings()
                .first()
            )
            if row is None:
                return None
            return _execution_from_row(row)

    async def get_transition(
        self, tenant: TenantContext, workflow_id: UUID, command_id: str
    ) -> WorkflowTransition | None:
        async with self._session_factory() as session:
            row = (
                (
                    await session.execute(
                        select(workflow_transition_table).where(
                            workflow_transition_table.c.tenant_id == tenant.tenant_id,
                            workflow_transition_table.c.workflow_id == workflow_id,
                            workflow_transition_table.c.command_id == command_id,
                        )
                    )
                )
                .mappings()
                .first()
            )
            if row is None:
                return None
            return _transition_from_row(row)

    async def list_transitions(
        self, tenant: TenantContext, workflow_id: UUID
    ) -> tuple[WorkflowTransition, ...]:
        async with self._session_factory() as session:
            rows = (
                (
                    await session.execute(
                        select(workflow_transition_table)
                        .where(
                            workflow_transition_table.c.tenant_id == tenant.tenant_id,
                            workflow_transition_table.c.workflow_id == workflow_id,
                        )
                        .order_by(workflow_transition_table.c.sequence)
                    )
                )
                .mappings()
                .all()
            )
            return tuple(_transition_from_row(row) for row in rows)

    async def count_transitions(
        self,
        tenant: TenantContext,
        workflow_id: UUID,
        *,
        command_id: str | None = None,
    ) -> int:
        stmt = select(func.count()).select_from(workflow_transition_table).where(
            workflow_transition_table.c.tenant_id == tenant.tenant_id,
            workflow_transition_table.c.workflow_id == workflow_id,
        )
        if command_id is not None:
            stmt = stmt.where(workflow_transition_table.c.command_id == command_id)
        async with self._session_factory() as session:
            value = await session.scalar(stmt)
            return int(value or 0)

    async def cas_advance(
        self,
        tenant: TenantContext,
        expected_lock_version: int,
        execution: WorkflowExecution,
        transition: WorkflowTransition,
        outbox: OutboxEvent,
    ) -> WorkflowExecution:
        if execution.tenant_id != tenant.tenant_id:
            raise WorkflowError("not_found", "Resource not found")
        try:
            async with self._session_factory() as session, session.begin():
                row = (
                    (
                        await session.execute(
                            workflow_execution_table.update()
                            .where(
                                workflow_execution_table.c.tenant_id
                                == tenant.tenant_id,
                                workflow_execution_table.c.id == execution.id,
                                workflow_execution_table.c.lock_version
                                == expected_lock_version,
                            )
                            .values(
                                state=execution.state,
                                status=execution.status,
                                data=dict(execution.data),
                                error=execution.error,
                                lock_version=execution.lock_version,
                                updated_at=execution.updated_at,
                            )
                            .returning(workflow_execution_table)
                        )
                    )
                    .mappings()
                    .first()
                )
                if row is None:
                    existing = (
                        (
                            await session.execute(
                                select(workflow_execution_table.c.id).where(
                                    workflow_execution_table.c.tenant_id
                                    == tenant.tenant_id,
                                    workflow_execution_table.c.id == execution.id,
                                )
                            )
                        )
                        .first()
                    )
                    if existing is None:
                        raise WorkflowError("not_found", "Resource not found")
                    raise WorkflowError(
                        "conflict", "Workflow was updated concurrently."
                    )
                await session.execute(
                    workflow_transition_table.insert().values(
                        **_transition_values(transition)
                    )
                )
                await session.execute(
                    outbox_event_table.insert().values(**_outbox_values(outbox))
                )
                return _execution_from_row(row)
        except IntegrityError as exc:
            raise WorkflowError(
                "conflict", "Workflow was updated concurrently."
            ) from exc
