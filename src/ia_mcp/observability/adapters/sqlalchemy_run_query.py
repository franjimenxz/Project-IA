from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Literal, assert_never, cast
from uuid import UUID, uuid4

from sqlalchemy import or_, select
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from ia_mcp.agent_runtime.run_repository import agent_run_table
from ia_mcp.configuration.adapters.sqlalchemy import audit_event_table
from ia_mcp.conversation.adapters.sqlalchemy import conversation_table, message_table
from ia_mcp.handoff.models import sanitize_text
from ia_mcp.handoff.service import handoff_table
from ia_mcp.mcp.audit import sanitize_summary
from ia_mcp.observability.redaction import redact
from ia_mcp.observability.run_models import (
    AuditEventSummary,
    ConversationSummary,
    HandoffSummary,
    JobSummary,
    RetrievalSummary,
    RunInvestigation,
    RunSummary,
    TimelineEvent,
    TimelineKind,
    ToolExecutionSummary,
    WorkflowSummary,
)
from ia_mcp.observability.run_query import (
    AUDIT_INVESTIGATION_ACTION,
    DEFAULT_PAGE_SIZE,
    INVESTIGATION_ACTOR_ID,
    RunNotFound,
    clamp_page_size,
)
from ia_mcp.scheduling.service import scheduled_job_table
from ia_mcp.tenancy.models import TenantContext
from ia_mcp.workflows.adapters.sqlalchemy import (
    workflow_execution_table,
    workflow_transition_table,
)
from ia_mcp.workflows.models import sanitize_payload

_BLOCKED_PAYLOAD_KEYS = frozenset(
    {
        "text",
        "chunk",
        "content",
        "prompt",
        "completion",
        "body",
        "payload",
        "arguments",
        "request",
        "response",
        "patient",
        "patient_reference",
        "dni",
        "email",
        "phone",
        "notes",
        "collected_fields",
        "authorization",
    }
)

type _TransitionClass = Literal["retrieval", "tool", "retry", "transition"]


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _mapping(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        return {}
    return {str(key): item for key, item in value.items()}


def _as_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _token_count(usage: object, key: str) -> int | None:
    return _as_int(_mapping(usage).get(key))


def _sanitize_mapping(raw: Mapping[str, object] | None) -> dict[str, object]:
    blocked = {
        key: value
        for key, value in _mapping(raw).items()
        if key.lower() not in _BLOCKED_PAYLOAD_KEYS
    }
    cleaned = sanitize_summary(sanitize_payload(blocked))
    redacted: dict[str, object] = {}
    for key, value in cleaned.items():
        if isinstance(value, str):
            redacted[key] = redact(value)
            continue
        if isinstance(value, Mapping):
            redacted[key] = _sanitize_mapping(value)
            continue
        redacted[key] = value
    return redacted


def _classify(event_type: str) -> _TransitionClass:
    if event_type == "knowledge.search":
        return "retrieval"
    if event_type == "retry" or event_type.endswith(".retry"):
        return "retry"
    if event_type == "tool.execute" or event_type.startswith("tool."):
        return "tool"
    return "transition"


def _encode_cursor(occurred_at: datetime, ident: str) -> str:
    return f"{_utc(occurred_at).isoformat()}|{ident}"


def _decode_cursor(raw: str | None) -> tuple[datetime, str] | None:
    if raw is None or "|" not in raw:
        return None
    stamp, _, ident = raw.partition("|")
    try:
        return _utc(datetime.fromisoformat(stamp)), ident
    except ValueError:
        return None


def _after_cursor(
    occurred_at: datetime, ident: str, cursor: tuple[datetime, str] | None
) -> bool:
    if cursor is None:
        return True
    cursor_at, cursor_ident = cursor
    stamp = _utc(occurred_at)
    if stamp > cursor_at:
        return True
    if stamp < cursor_at:
        return False
    return ident > cursor_ident


def _page[T](
    items: Sequence[T],
    *,
    occurred_at: Sequence[datetime],
    ident: Sequence[str],
    cursor: str | None,
    limit: int,
) -> tuple[tuple[T, ...], str | None]:
    decoded = _decode_cursor(cursor)
    selected: list[T] = []
    keys: list[tuple[datetime, str]] = []
    for item, stamp, key in zip(items, occurred_at, ident, strict=True):
        if not _after_cursor(stamp, key, decoded):
            continue
        selected.append(item)
        keys.append((_utc(stamp), key))
        if len(selected) > limit:
            break
    if len(selected) > limit:
        selected = selected[:limit]
        keys = keys[:limit]
        next_cursor = _encode_cursor(keys[-1][0], keys[-1][1])
        return tuple(selected), next_cursor
    return tuple(selected), None


def _timeline_label(kind: TimelineKind, detail: str) -> str:
    match kind:
        case "run_started":
            return "run started"
        case "run_finished":
            return "run finished"
        case "transition":
            return detail
        case "retry":
            return "retry"
        case "job":
            return "job"
        case "tool":
            return detail
        case "handoff":
            return "handoff"
        case "retrieval":
            return "retrieval"
        case _ as unreachable:
            assert_never(unreachable)


def _latency_ms(started_at: datetime, finished_at: datetime | None) -> int | None:
    if finished_at is None:
        return None
    delta = _utc(finished_at) - _utc(started_at)
    return int(delta.total_seconds() * 1000)


class SqlAlchemyRunInvestigationQuery:
    def __init__(self, engine: AsyncEngine) -> None:
        self._session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def get(
        self,
        tenant: TenantContext,
        run_id: UUID,
        *,
        tools_cursor: str | None = None,
        tools_limit: int = DEFAULT_PAGE_SIZE,
        events_cursor: str | None = None,
        events_limit: int = DEFAULT_PAGE_SIZE,
    ) -> RunInvestigation:
        tool_limit = clamp_page_size(tools_limit)
        event_limit = clamp_page_size(events_limit)
        async with self._session_factory() as session, session.begin():
            run_row = (
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
            if run_row is None:
                raise RunNotFound()
            conversation = await self._conversation(session, tenant, run_row)
            transitions = await self._transitions(session, tenant, run_id)
            workflow = await self._workflow(session, tenant, transitions)
            retrievals, tools, retry_events, other_transitions = self._from_transitions(
                transitions
            )
            paged_tools, tools_next = _page(
                tools,
                occurred_at=[item.occurred_at for item in tools],
                ident=[f"{item.sequence:020d}" for item in tools],
                cursor=tools_cursor,
                limit=tool_limit,
            )
            handoff = await self._handoff(session, tenant, run_row["conversation_id"])
            jobs = await self._jobs(session, tenant, run_row)
            audits = await self._audits(session, tenant, run_row)
            paged_audits, audit_next = _page(
                audits,
                occurred_at=[item.created_at for item in audits],
                ident=[str(item.id) for item in audits],
                cursor=events_cursor,
                limit=event_limit,
            )
            investigation = RunInvestigation(
                run=_run_summary(run_row),
                conversation=conversation,
                retrievals=tuple(retrievals),
                workflow=workflow,
                tools=paged_tools,
                handoff=handoff,
                jobs=tuple(jobs),
                audit_events=paged_audits,
                trace_url=None,
                timeline=_timeline(
                    run_row,
                    retrievals=retrievals,
                    tools=tools,
                    retries=retry_events,
                    transitions=other_transitions,
                    jobs=jobs,
                    handoff=handoff,
                ),
                tools_next_cursor=tools_next,
                audit_next_cursor=audit_next,
            )
            await session.execute(
                audit_event_table.insert().values(
                    id=uuid4(),
                    tenant_id=tenant.tenant_id,
                    actor_id=INVESTIGATION_ACTOR_ID,
                    action=AUDIT_INVESTIGATION_ACTION,
                    version=tenant.config_version,
                    created_at=datetime.now(UTC),
                )
            )
            return investigation

    async def _conversation(
        self,
        session: AsyncSession,
        tenant: TenantContext,
        run_row: RowMapping,
    ) -> ConversationSummary:
        conversation_id = cast(UUID, run_row["conversation_id"])
        trigger_id = cast(UUID, run_row["input_message_id"])
        conv = (
            (
                await session.execute(
                    select(
                        conversation_table.c.id,
                        conversation_table.c.status,
                        conversation_table.c.last_message_at,
                    ).where(
                        conversation_table.c.tenant_id == tenant.tenant_id,
                        conversation_table.c.id == conversation_id,
                    )
                )
            )
            .mappings()
            .first()
        )
        message = (
            (
                await session.execute(
                    select(
                        message_table.c.id,
                        message_table.c.direction,
                        message_table.c.content_type,
                    ).where(
                        message_table.c.tenant_id == tenant.tenant_id,
                        message_table.c.id == trigger_id,
                    )
                )
            )
            .mappings()
            .first()
        )
        last_message_at = (
            _utc(conv["last_message_at"])
            if conv is not None
            else _utc(run_row["started_at"])
        )
        return ConversationSummary(
            id=conversation_id,
            status=str(conv["status"]) if conv is not None else "unknown",
            last_message_at=last_message_at,
            trigger_message_id=trigger_id,
            trigger_direction=(
                str(message["direction"]) if message is not None else "unknown"
            ),
            trigger_content_type=(
                str(message["content_type"]) if message is not None else "unknown"
            ),
        )

    async def _transitions(
        self,
        session: AsyncSession,
        tenant: TenantContext,
        run_id: UUID,
    ) -> list[RowMapping]:
        rows = (
            (
                await session.execute(
                    select(workflow_transition_table)
                    .where(
                        workflow_transition_table.c.tenant_id == tenant.tenant_id,
                        workflow_transition_table.c.run_id == run_id,
                    )
                    .order_by(
                        workflow_transition_table.c.timestamp,
                        workflow_transition_table.c.sequence,
                    )
                )
            )
            .mappings()
            .all()
        )
        return list(rows)

    async def _workflow(
        self,
        session: AsyncSession,
        tenant: TenantContext,
        transitions: Sequence[RowMapping],
    ) -> WorkflowSummary | None:
        if not transitions:
            return None
        workflow_id = cast(UUID, transitions[0]["workflow_id"])
        row = (
            (
                await session.execute(
                    select(
                        workflow_execution_table.c.id,
                        workflow_execution_table.c.type,
                        workflow_execution_table.c.state,
                        workflow_execution_table.c.status,
                        workflow_execution_table.c.error,
                        workflow_execution_table.c.schema_version,
                    ).where(
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
        return WorkflowSummary(
            id=row["id"],
            type=str(row["type"]),
            state=str(row["state"]),
            status=str(row["status"]),
            error=sanitize_text(row["error"] if isinstance(row["error"], str) else None),
            schema_version=int(row["schema_version"]),
        )

    def _from_transitions(
        self, transitions: Sequence[RowMapping]
    ) -> tuple[
        list[RetrievalSummary],
        list[ToolExecutionSummary],
        list[tuple[datetime, str]],
        list[tuple[datetime, str]],
    ]:
        retrievals: list[RetrievalSummary] = []
        tools: list[ToolExecutionSummary] = []
        retries: list[tuple[datetime, str]] = []
        others: list[tuple[datetime, str]] = []
        for row in transitions:
            event_type = str(row["event_type"])
            occurred_at = _utc(row["timestamp"])
            payload = _sanitize_mapping(_mapping(row["payload"]))
            raw = _mapping(row["payload"])
            kind = _classify(event_type)
            if kind == "retrieval":
                source_ids = raw.get("source_ids")
                if isinstance(source_ids, list):
                    for item in source_ids:
                        if isinstance(item, str) and item:
                            retrievals.append(
                                RetrievalSummary(
                                    source_id=redact(item), occurred_at=occurred_at
                                )
                            )
                continue
            if kind == "tool":
                tool_name = payload.get("tool_name")
                if not isinstance(tool_name, str) or not tool_name:
                    continue
                mcp_id = payload.get("mcp_server_id")
                status = payload.get("status")
                error_code = payload.get("error_code")
                retry_count = _as_int(payload.get("retry_count")) or 0
                tools.append(
                    ToolExecutionSummary(
                        tool_name=tool_name,
                        mcp_server_id=mcp_id if isinstance(mcp_id, str) else None,
                        status=status if isinstance(status, str) else "unknown",
                        error_code=(
                            error_code if isinstance(error_code, str) else None
                        ),
                        occurred_at=occurred_at,
                        retry_count=retry_count,
                        sequence=int(row["sequence"]),
                    )
                )
                continue
            if kind == "retry":
                retries.append((occurred_at, str(row["sequence"])))
                continue
            others.append((occurred_at, event_type))
        return retrievals, tools, retries, others

    async def _handoff(
        self,
        session: AsyncSession,
        tenant: TenantContext,
        conversation_id: UUID,
    ) -> HandoffSummary | None:
        row = (
            (
                await session.execute(
                    select(
                        handoff_table.c.id,
                        handoff_table.c.status,
                        handoff_table.c.reason,
                        handoff_table.c.requested_at,
                        handoff_table.c.accepted_at,
                        handoff_table.c.resolved_at,
                    )
                    .where(
                        handoff_table.c.tenant_id == tenant.tenant_id,
                        handoff_table.c.conversation_id == conversation_id,
                    )
                    .order_by(handoff_table.c.requested_at.desc())
                    .limit(1)
                )
            )
            .mappings()
            .first()
        )
        if row is None:
            return None
        return HandoffSummary(
            id=row["id"],
            status=str(row["status"]),
            reason=str(row["reason"]),
            requested_at=_utc(row["requested_at"]),
            accepted_at=_utc(row["accepted_at"]) if row["accepted_at"] else None,
            resolved_at=_utc(row["resolved_at"]) if row["resolved_at"] else None,
        )

    async def _jobs(
        self,
        session: AsyncSession,
        tenant: TenantContext,
        run_row: RowMapping,
    ) -> list[JobSummary]:
        correlation = str(run_row["correlation_id"])
        started = _utc(run_row["started_at"])
        finished = run_row["finished_at"]
        end = _utc(finished) if finished is not None else started
        rows = (
            (
                await session.execute(
                    select(
                        scheduled_job_table.c.id,
                        scheduled_job_table.c.type,
                        scheduled_job_table.c.status,
                        scheduled_job_table.c.attempts,
                        scheduled_job_table.c.scheduled_for,
                        scheduled_job_table.c.created_at,
                        scheduled_job_table.c.last_error,
                    )
                    .where(
                        scheduled_job_table.c.tenant_id == tenant.tenant_id,
                        scheduled_job_table.c.created_at >= started,
                        scheduled_job_table.c.created_at <= end,
                        or_(
                            scheduled_job_table.c.payload["correlation_id"].as_string()
                            == correlation,
                            scheduled_job_table.c.payload["telemetry"][
                                "correlation_id"
                            ].as_string()
                            == correlation,
                        ),
                    )
                    .order_by(scheduled_job_table.c.created_at)
                )
            )
            .mappings()
            .all()
        )
        jobs: list[JobSummary] = []
        for row in rows:
            jobs.append(
                JobSummary(
                    id=row["id"],
                    type=str(row["type"]),
                    status=str(row["status"]),
                    attempts=int(row["attempts"]),
                    scheduled_for=_utc(row["scheduled_for"]),
                    created_at=_utc(row["created_at"]),
                    last_error=sanitize_text(
                        row["last_error"]
                        if isinstance(row["last_error"], str)
                        else None
                    ),
                )
            )
        return jobs

    async def _audits(
        self,
        session: AsyncSession,
        tenant: TenantContext,
        run_row: RowMapping,
    ) -> list[AuditEventSummary]:
        started = _utc(run_row["started_at"])
        finished = run_row["finished_at"]
        end = _utc(finished) if finished is not None else started
        rows = (
            (
                await session.execute(
                    select(
                        audit_event_table.c.id,
                        audit_event_table.c.action,
                        audit_event_table.c.created_at,
                        audit_event_table.c.version,
                    )
                    .where(
                        audit_event_table.c.tenant_id == tenant.tenant_id,
                        audit_event_table.c.created_at >= started,
                        audit_event_table.c.created_at <= end,
                    )
                    .order_by(
                        audit_event_table.c.created_at, audit_event_table.c.id
                    )
                )
            )
            .mappings()
            .all()
        )
        return [
            AuditEventSummary(
                id=row["id"],
                action=str(row["action"]),
                created_at=_utc(row["created_at"]),
                version=int(row["version"]) if row["version"] is not None else None,
            )
            for row in rows
        ]


def _run_summary(row: RowMapping) -> RunSummary:
    started = _utc(row["started_at"])
    finished = _utc(row["finished_at"]) if row["finished_at"] is not None else None
    return RunSummary(
        id=row["id"],
        conversation_id=row["conversation_id"],
        config_version=int(row["config_version"]),
        skill=row["skill"],
        workflow_type=row["workflow_type"],
        mcp_server_id=row["mcp_server_id"],
        status=str(row["status"]),
        error_code=row["error_code"],
        model_provider=row["model_provider"],
        model_name=row["model_name"],
        started_at=started,
        finished_at=finished,
        latency_ms=_latency_ms(started, finished),
        input_tokens=_token_count(row["usage"], "input_tokens"),
        output_tokens=_token_count(row["usage"], "output_tokens"),
        correlation_id=row["correlation_id"],
    )


def _timeline(
    run_row: RowMapping,
    *,
    retrievals: Sequence[RetrievalSummary],
    tools: Sequence[ToolExecutionSummary],
    retries: Sequence[tuple[datetime, str]],
    transitions: Sequence[tuple[datetime, str]],
    jobs: Sequence[JobSummary],
    handoff: HandoffSummary | None,
) -> tuple[TimelineEvent, ...]:
    events: list[TimelineEvent] = [
        TimelineEvent(
            occurred_at=_utc(run_row["started_at"]),
            kind="run_started",
            label=_timeline_label("run_started", ""),
            ref=str(run_row["id"]),
        )
    ]
    if run_row["finished_at"] is not None:
        events.append(
            TimelineEvent(
                occurred_at=_utc(run_row["finished_at"]),
                kind="run_finished",
                label=_timeline_label("run_finished", ""),
                ref=str(run_row["id"]),
                error_code=run_row["error_code"],
            )
        )
    for retrieval in retrievals:
        events.append(
            TimelineEvent(
                occurred_at=retrieval.occurred_at,
                kind="retrieval",
                label=_timeline_label("retrieval", retrieval.source_id),
                ref=retrieval.source_id,
            )
        )
    for tool in tools:
        events.append(
            TimelineEvent(
                occurred_at=tool.occurred_at,
                kind="tool",
                label=_timeline_label("tool", tool.tool_name),
                ref=tool.tool_name,
                error_code=tool.error_code,
            )
        )
    for occurred_at, ref in retries:
        events.append(
            TimelineEvent(
                occurred_at=occurred_at,
                kind="retry",
                label=_timeline_label("retry", ref),
                ref=ref,
            )
        )
    for occurred_at, event_type in transitions:
        events.append(
            TimelineEvent(
                occurred_at=occurred_at,
                kind="transition",
                label=_timeline_label("transition", event_type),
                ref=event_type,
            )
        )
    for job in jobs:
        events.append(
            TimelineEvent(
                occurred_at=job.created_at,
                kind="job",
                label=_timeline_label("job", job.type),
                ref=str(job.id),
            )
        )
    if handoff is not None:
        events.append(
            TimelineEvent(
                occurred_at=handoff.requested_at,
                kind="handoff",
                label=_timeline_label("handoff", handoff.reason),
                ref=str(handoff.id),
            )
        )
    events.sort(key=lambda item: (item.occurred_at, item.kind, item.ref))
    return tuple(events)
