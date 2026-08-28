from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy import (
    Column,
    DateTime,
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

from ia_mcp.conversation.adapters.sqlalchemy import conversation_table
from ia_mcp.handoff.models import (
    HANDOFF_REASONS,
    HandoffCase,
    HandoffDelivery,
    HandoffOutbox,
    HandoffReason,
    HandoffRequest,
    HandoffResult,
    HandoffStatus,
    HandoffSummary,
    sanitize_fields,
    sanitize_text,
)
from ia_mcp.handoff.ports import HandoffError, HandoffProvider, HandoffRepository
from ia_mcp.tenancy.models import TenantContext
from ia_mcp.workflows.adapters.sqlalchemy import outbox_event_table

metadata = MetaData()

handoff_table = Table(
    "handoff",
    metadata,
    Column("tenant_id", PGUUID(as_uuid=True), nullable=False),
    Column("id", PGUUID(as_uuid=True), nullable=False),
    Column("conversation_id", PGUUID(as_uuid=True), nullable=False),
    Column("workflow_id", PGUUID(as_uuid=True), nullable=True),
    Column("reason", String(64), nullable=False),
    Column("summary", JSONB, nullable=False),
    Column("business_key", String(255), nullable=False),
    Column("status", String(32), nullable=False),
    Column("external_case_reference", String(255), nullable=True),
    Column("owner_reference", String(255), nullable=True),
    Column("requested_at", DateTime(timezone=True), nullable=False),
    Column("accepted_at", DateTime(timezone=True), nullable=True),
    Column("resolved_at", DateTime(timezone=True), nullable=True),
    PrimaryKeyConstraint("tenant_id", "id"),
    UniqueConstraint(
        "tenant_id",
        "business_key",
        name="uq_handoff_tenant_business_key",
    ),
)


def _now() -> datetime:
    return datetime.now(UTC)


def _payload(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    return {str(key): item for key, item in value.items()}


def _summary_from_payload(payload: dict[str, object]) -> HandoffSummary:
    workflow_raw = payload.get("active_workflow_id")
    workflow_id = UUID(workflow_raw) if isinstance(workflow_raw, str) and workflow_raw else None
    collected = payload.get("collected_fields")
    actions = payload.get("completed_actions")
    reason = cast(HandoffReason, payload.get("reason", "explicit_request"))
    patient = payload.get("patient_reference")
    notes = payload.get("notes")
    return HandoffSummary(
        patient_reference=patient if isinstance(patient, str) else None,
        reason=reason,
        collected_fields=_payload(collected) if collected is not None else {},
        completed_actions=tuple(str(item) for item in actions) if isinstance(actions, list) else (),
        active_workflow_id=workflow_id,
        notes=notes if isinstance(notes, str) else None,
    )


def _case_from_row(row: Any) -> HandoffCase:
    return HandoffCase(
        tenant_id=row["tenant_id"],
        id=row["id"],
        conversation_id=row["conversation_id"],
        workflow_id=row["workflow_id"],
        reason=cast(HandoffReason, row["reason"]),
        summary=_summary_from_payload(_payload(row["summary"])),
        business_key=row["business_key"],
        status=cast(HandoffStatus, row["status"]),
        external_case_reference=row["external_case_reference"],
        owner_reference=row["owner_reference"],
        requested_at=row["requested_at"],
        accepted_at=row["accepted_at"],
        resolved_at=row["resolved_at"],
    )


def _case_values(case: HandoffCase) -> dict[str, object]:
    return {
        "tenant_id": case.tenant_id,
        "id": case.id,
        "conversation_id": case.conversation_id,
        "workflow_id": case.workflow_id,
        "reason": case.reason,
        "summary": case.summary.as_payload(),
        "business_key": case.business_key,
        "status": case.status,
        "external_case_reference": case.external_case_reference,
        "owner_reference": case.owner_reference,
        "requested_at": case.requested_at,
        "accepted_at": case.accepted_at,
        "resolved_at": case.resolved_at,
    }


def build_summary(request: HandoffRequest) -> HandoffSummary:
    return HandoffSummary(
        patient_reference=sanitize_text(request.patient_reference),
        reason=request.reason,
        collected_fields=sanitize_fields(request.collected_fields),
        completed_actions=request.completed_actions,
        active_workflow_id=request.active_workflow_id,
        notes=sanitize_text(request.notes),
    )


def _to_result(
    case: HandoffCase, *, replayed: bool, delivery_pending: bool
) -> HandoffResult:
    return HandoffResult(
        handoff_id=case.id,
        conversation_id=case.conversation_id,
        tenant_id=case.tenant_id,
        reason=case.reason,
        status=case.status,
        summary=case.summary,
        business_key=case.business_key,
        replayed=replayed,
        delivery_pending=delivery_pending,
    )


class SqlAlchemyHandoffRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self._session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def get(
        self, tenant: TenantContext, handoff_id: UUID
    ) -> HandoffCase | None:
        async with self._session_factory() as session:
            row = (
                (
                    await session.execute(
                        select(handoff_table).where(
                            handoff_table.c.tenant_id == tenant.tenant_id,
                            handoff_table.c.id == handoff_id,
                        )
                    )
                )
                .mappings()
                .first()
            )
            if row is None:
                return None
            return _case_from_row(row)

    async def get_by_business_key(
        self, tenant: TenantContext, business_key: str
    ) -> HandoffCase | None:
        async with self._session_factory() as session:
            row = (
                (
                    await session.execute(
                        select(handoff_table).where(
                            handoff_table.c.tenant_id == tenant.tenant_id,
                            handoff_table.c.business_key == business_key,
                        )
                    )
                )
                .mappings()
                .first()
            )
            if row is None:
                return None
            return _case_from_row(row)

    async def count_cases(self, tenant: TenantContext) -> int:
        async with self._session_factory() as session:
            value = await session.scalar(
                select(func.count())
                .select_from(handoff_table)
                .where(handoff_table.c.tenant_id == tenant.tenant_id)
            )
            return int(value or 0)

    async def create_with_ownership(
        self,
        tenant: TenantContext,
        case: HandoffCase,
        outbox: HandoffOutbox,
        conversation_id: UUID,
    ) -> HandoffCase:
        if case.tenant_id != tenant.tenant_id:
            raise HandoffError("not_found", "Resource not found")
        try:
            async with self._session_factory() as session, session.begin():
                updated = (
                    (
                        await session.execute(
                            conversation_table.update()
                            .where(
                                conversation_table.c.tenant_id == tenant.tenant_id,
                                conversation_table.c.id == conversation_id,
                            )
                            .values(
                                status="human_owned",
                                lock_version=conversation_table.c.lock_version + 1,
                            )
                            .returning(conversation_table.c.id)
                        )
                    )
                    .first()
                )
                if updated is None:
                    raise HandoffError("not_found", "Resource not found")
                await session.execute(handoff_table.insert().values(**_case_values(case)))
                await session.execute(
                    outbox_event_table.insert().values(
                        tenant_id=outbox.tenant_id,
                        id=outbox.id,
                        kind=outbox.kind,
                        payload=dict(outbox.payload),
                        created_at=outbox.created_at,
                    )
                )
                return case
        except IntegrityError as exc:
            raise HandoffError("conflict", "Handoff already exists.") from exc


class HandoffService:
    def __init__(
        self, repository: HandoffRepository, provider: HandoffProvider
    ) -> None:
        self._repository = repository
        self._provider = provider

    async def create(
        self, tenant: TenantContext, request: HandoffRequest
    ) -> HandoffResult:
        if request.reason not in HANDOFF_REASONS:
            raise HandoffError("invalid_reason", "Handoff reason is not allowed.")
        existing = await self._repository.get_by_business_key(
            tenant, request.business_key
        )
        if existing is not None:
            return _to_result(existing, replayed=True, delivery_pending=False)
        now = _now()
        summary = build_summary(request)
        case = HandoffCase(
            tenant_id=tenant.tenant_id,
            id=uuid4(),
            conversation_id=request.conversation_id,
            workflow_id=request.active_workflow_id,
            reason=request.reason,
            summary=summary,
            business_key=request.business_key,
            status="requested",
            external_case_reference=None,
            owner_reference=None,
            requested_at=now,
            accepted_at=None,
            resolved_at=None,
        )
        outbox = HandoffOutbox(
            tenant_id=tenant.tenant_id,
            id=uuid4(),
            kind="handoff.requested",
            payload={
                "handoff_id": str(case.id),
                "conversation_id": str(case.conversation_id),
                "reason": case.reason,
                "summary": summary.as_payload(),
                "business_key": case.business_key,
            },
            created_at=now,
        )
        try:
            stored = await self._repository.create_with_ownership(
                tenant, case, outbox, request.conversation_id
            )
        except HandoffError as exc:
            if exc.code == "conflict":
                replayed = await self._repository.get_by_business_key(
                    tenant, request.business_key
                )
                if replayed is not None:
                    return _to_result(replayed, replayed=True, delivery_pending=False)
            raise
        delivery = HandoffDelivery(
            handoff_id=stored.id,
            conversation_id=stored.conversation_id,
            reason=stored.reason,
            summary=stored.summary,
            business_key=stored.business_key,
        )
        try:
            await self._provider.transfer(tenant, delivery)
        except HandoffError as exc:
            if exc.code == "provider_unavailable":
                return _to_result(stored, replayed=False, delivery_pending=True)
            raise
        return _to_result(stored, replayed=False, delivery_pending=False)
