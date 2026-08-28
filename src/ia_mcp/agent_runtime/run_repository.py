from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, cast
from uuid import UUID, uuid4

from sqlalchemy import (
    Column,
    DateTime,
    Integer,
    MetaData,
    PrimaryKeyConstraint,
    String,
    Table,
    UniqueConstraint,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from ia_mcp.tenancy.models import TenantContext

type AgentRunStatus = Literal["started", "succeeded", "failed", "handed_off"]

SAFE_FAILED_MESSAGE = "An internal error occurred"
SYSTEM_ACTOR_ID = UUID("00000000-0000-4000-8000-000000000000")

metadata = MetaData()

agent_run_table = Table(
    "agent_run",
    metadata,
    Column("id", PGUUID(as_uuid=True), nullable=False),
    Column("tenant_id", PGUUID(as_uuid=True), nullable=False),
    Column("conversation_id", PGUUID(as_uuid=True), nullable=False),
    Column("config_version", Integer, nullable=False),
    Column("correlation_id", PGUUID(as_uuid=True), nullable=False),
    Column("input_message_id", PGUUID(as_uuid=True), nullable=False),
    Column("model_provider", String(64), nullable=True),
    Column("model_name", String(128), nullable=True),
    Column("skill", String(64), nullable=True),
    Column("workflow_type", String(64), nullable=True),
    Column("mcp_server_id", String(128), nullable=True),
    Column("status", String(32), nullable=False),
    Column("usage", JSONB, nullable=True),
    Column("started_at", DateTime(timezone=True), nullable=False),
    Column("finished_at", DateTime(timezone=True), nullable=True),
    Column("error_code", String(64), nullable=True),
    PrimaryKeyConstraint("tenant_id", "id"),
    UniqueConstraint(
        "tenant_id",
        "input_message_id",
        name="uq_agent_run_tenant_input_message",
    ),
)


@dataclass(frozen=True, slots=True)
class AgentRun:
    id: UUID
    tenant_id: UUID
    conversation_id: UUID
    config_version: int
    correlation_id: UUID
    input_message_id: UUID
    status: AgentRunStatus
    started_at: datetime
    finished_at: datetime | None
    error_code: str | None
    model_provider: str | None = None
    model_name: str | None = None
    skill: str | None = None


@dataclass(frozen=True, slots=True)
class AgentRunResult:
    run: AgentRun
    safe_message: str | None


class AgentRunError(Exception):
    def __init__(self, code: str, safe_message: str) -> None:
        self.code = code
        self.safe_message = safe_message
        super().__init__(safe_message)


def _now() -> datetime:
    return datetime.now(UTC)


def _run_from_row(row: Any) -> AgentRun:
    return AgentRun(
        id=row["id"],
        tenant_id=row["tenant_id"],
        conversation_id=row["conversation_id"],
        config_version=int(row["config_version"]),
        correlation_id=row["correlation_id"],
        input_message_id=row["input_message_id"],
        status=cast(AgentRunStatus, row["status"]),
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        error_code=row["error_code"],
        model_provider=row["model_provider"],
        model_name=row["model_name"],
        skill=row["skill"],
    )


class SqlAlchemyAgentRunRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self._session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def start(
        self,
        tenant: TenantContext,
        conversation_id: UUID,
        input_message_id: UUID,
        *,
        skill: str | None = None,
        model_provider: str | None = None,
        model_name: str | None = None,
    ) -> AgentRun:
        try:
            async with self._session_factory() as session, session.begin():
                inserted = (
                    (
                        await session.execute(
                            pg_insert(agent_run_table)
                            .values(
                                id=uuid4(),
                                tenant_id=tenant.tenant_id,
                                conversation_id=conversation_id,
                                config_version=tenant.config_version,
                                correlation_id=tenant.correlation_id,
                                input_message_id=input_message_id,
                                model_provider=model_provider,
                                model_name=model_name,
                                skill=skill,
                                workflow_type=None,
                                mcp_server_id=None,
                                status="started",
                                usage=None,
                                started_at=_now(),
                                finished_at=None,
                                error_code=None,
                            )
                            .on_conflict_do_nothing(
                                constraint="uq_agent_run_tenant_input_message"
                            )
                            .returning(agent_run_table)
                        )
                    )
                    .mappings()
                    .first()
                )
                if inserted is not None:
                    return _run_from_row(inserted)
                existing = (
                    (
                        await session.execute(
                            select(agent_run_table).where(
                                agent_run_table.c.tenant_id == tenant.tenant_id,
                                agent_run_table.c.input_message_id == input_message_id,
                            )
                        )
                    )
                    .mappings()
                    .first()
                )
                if existing is None:
                    raise AgentRunError("not_found", "Resource not found")
                return _run_from_row(existing)
        except IntegrityError as exc:
            raise AgentRunError("not_found", "Resource not found") from exc

    async def finish(
        self,
        tenant: TenantContext,
        run_id: UUID,
        status: AgentRunStatus,
        *,
        error_code: str | None = None,
        usage: dict[str, Any] | None = None,
        error_detail: str | None = None,
    ) -> AgentRunResult:
        del error_detail
        if status == "started":
            raise AgentRunError("validation_error", "Run cannot finish as started.")
        safe_message = SAFE_FAILED_MESSAGE if status == "failed" else None
        async with self._session_factory() as session, session.begin():
            current = (
                (
                    await session.execute(
                        select(agent_run_table)
                        .where(
                            agent_run_table.c.tenant_id == tenant.tenant_id,
                            agent_run_table.c.id == run_id,
                        )
                        .with_for_update()
                    )
                )
                .mappings()
                .first()
            )
            if current is None:
                raise AgentRunError("not_found", "Resource not found")
            if current["status"] != "started":
                run = _run_from_row(current)
                return AgentRunResult(
                    run=run,
                    safe_message=(
                        SAFE_FAILED_MESSAGE if run.status == "failed" else None
                    ),
                )
            row = (
                (
                    await session.execute(
                        agent_run_table.update()
                        .where(
                            agent_run_table.c.tenant_id == tenant.tenant_id,
                            agent_run_table.c.id == run_id,
                        )
                        .values(
                            status=status,
                            finished_at=_now(),
                            error_code=error_code,
                            usage=usage,
                        )
                        .returning(agent_run_table)
                    )
                )
                .mappings()
                .first()
            )
            if row is None:
                raise AgentRunError("not_found", "Resource not found")
            if status == "failed":
                await session.execute(
                    text(
                        """
                        INSERT INTO audit_event (
                            id, tenant_id, actor_id, action, version, created_at
                        )
                        VALUES (
                            :id, :tenant_id, :actor_id, :action, :version, :created_at
                        )
                        """
                    ),
                    {
                        "id": uuid4(),
                        "tenant_id": tenant.tenant_id,
                        "actor_id": SYSTEM_ACTOR_ID,
                        "action": "agent_run_failed",
                        "version": int(row["config_version"]),
                        "created_at": _now(),
                    },
                )
            return AgentRunResult(run=_run_from_row(row), safe_message=safe_message)

    async def get(self, tenant: TenantContext, run_id: UUID) -> AgentRun | None:
        async with self._session_factory() as session:
            row = (
                (
                    await session.execute(
                        select(agent_run_table).where(
                            agent_run_table.c.tenant_id == tenant.tenant_id,
                            agent_run_table.c.id == run_id,
                        )
                    )
                )
                .mappings()
                .first()
            )
            if row is None:
                return None
            return _run_from_row(row)
