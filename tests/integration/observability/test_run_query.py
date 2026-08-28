"""AC-P07-001/002/004/005: tenant-scoped run investigation read model."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, select, text, update
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from alembic import command
from ia_mcp.agent_runtime.run_repository import (
    SqlAlchemyAgentRunRepository,
    agent_run_table,
)
from ia_mcp.configuration.adapters.sqlalchemy import (
    audit_event_table,
    channel_integration_table,
    tenant_table,
)
from ia_mcp.conversation.adapters.sqlalchemy import (
    SqlAlchemyConversationRepository,
    conversation_table,
    message_table,
)
from ia_mcp.conversation.models import InboundMessage
from ia_mcp.handoff.service import handoff_table
from ia_mcp.knowledge.adapters.sqlalchemy import (
    knowledge_chunk_table,
    knowledge_document_table,
    knowledge_document_version_table,
)
from ia_mcp.observability.adapters.sqlalchemy_run_query import (
    SqlAlchemyRunInvestigationQuery,
)
from ia_mcp.observability.run_query import (
    AUDIT_INVESTIGATION_ACTION,
    InvalidCursor,
    RunNotFound,
)
from ia_mcp.scheduling.service import scheduled_job_table
from ia_mcp.tenancy.models import TenantContext
from ia_mcp.workflows.adapters.sqlalchemy import (
    workflow_execution_table,
    workflow_transition_table,
)

ROOT = Path(__file__).resolve().parents[3]
DATABASE_URL = "postgresql+psycopg://francojimenez@127.0.0.1:5432/ia_mcp_p02_t03"

TENANT_A = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
TENANT_B = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
CHANNEL_A = UUID("aa111111-1111-1111-1111-111111111111")
CHANNEL_B = UUID("bb111111-1111-1111-1111-111111111111")
CORR_A = UUID("33333333-3333-3333-3333-333333333333")
CORR_B = UUID("44444444-4444-4444-4444-444444444444")
ACTOR_A = UUID("aaaaaaaa-0000-4000-8000-00000000000a")

TENANT_A_CTX = TenantContext(
    tenant_id=TENANT_A,
    tenant_slug="tenant-a",
    config_version=1,
    correlation_id=CORR_A,
)
TENANT_B_CTX = TenantContext(
    tenant_id=TENANT_B,
    tenant_slug="tenant-b",
    config_version=1,
    correlation_id=CORR_B,
)

T_START = datetime(2026, 8, 28, 4, 20, 0, tzinfo=UTC)
T_SEARCH = T_START + timedelta(seconds=1)
T_TOOL = T_START + timedelta(seconds=2)
T_RETRY = T_START + timedelta(seconds=3)
T_TOOL2 = T_START + timedelta(seconds=4)
T_ADVANCE = T_START + timedelta(seconds=5)
T_JOB = T_START + timedelta(seconds=6)
T_HANDOFF = T_START + timedelta(seconds=7)
T_FINISH = T_START + timedelta(seconds=8)
T_AUDIT_1 = T_START + timedelta(seconds=2)
T_AUDIT_2 = T_START + timedelta(seconds=4)
T_AUDIT_3 = T_START + timedelta(seconds=6)
T_B_HANDOFF = T_HANDOFF + timedelta(milliseconds=500)
T_LATER_START = T_FINISH + timedelta(minutes=10)
T_LATER_HANDOFF = T_LATER_START + timedelta(seconds=3)
T_LATER_FINISH = T_LATER_START + timedelta(seconds=5)
T_INFLIGHT = T_START + timedelta(hours=3)
T_INFLIGHT_JOB = T_INFLIGHT + timedelta(seconds=5)

CORR_INFLIGHT = UUID("77777777-7777-4777-8777-777777777777")
INFLIGHT_CTX = TenantContext(
    tenant_id=TENANT_A,
    tenant_slug="tenant-a",
    config_version=1,
    correlation_id=CORR_INFLIGHT,
)

TENANT_B_TOOL = "tenant_b_tool"
TENANT_B_WORKFLOW_TYPE = "tenant_b_workflow"
TENANT_B_JOB_MARKER = "tenant_b_job_marker"
LATER_HANDOFF_REASON = "explicit_request"
WORKFLOW_ERROR = (
    "upstream timeout for Juan Perez patient@example.com Bearer secret-token"
)
JOB_LAST_ERROR = (
    "delivery failed Juan Perez patient@example.com Bearer secret-token"
)

MESSAGE_BODY = (
    "Necesito turno. DNI 30111222 patient@example.com Bearer secret-token"
)
CHUNK_TEXT = "FULL CHUNK Juan Perez DNI 30111222 private clinical note"
PROMPT = "System prompt api_key=sk-live-secret"
PATIENT_REF = "Juan Perez DNI 30111222"
SOURCE_ID = "kb:hours:1"
TOOL_ARGUMENTS = {"dni": "30111222", "authorization": "Bearer secret-token"}


@dataclass(frozen=True, slots=True)
class SeededRuns:
    run_a_id: UUID
    run_b_id: UUID
    sparse_run_id: UUID
    later_run_id: UUID
    inflight_run_id: UUID
    trigger_message_id: UUID


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


def _seed_tenants_and_channels() -> None:
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
        connection.execute(
            channel_integration_table.insert(),
            [
                {
                    "id": CHANNEL_A,
                    "tenant_id": TENANT_A,
                    "channel": "simulated",
                    "external_account_id": "acct-a",
                    "secret_reference": "secret://simulated/a",
                    "status": "active",
                },
                {
                    "id": CHANNEL_B,
                    "tenant_id": TENANT_B,
                    "channel": "simulated",
                    "external_account_id": "acct-b",
                    "secret_reference": "secret://simulated/b",
                    "status": "active",
                },
            ],
        )
    engine.dispose()


def _inbound(
    *,
    channel_integration_id: UUID,
    channel_account_id: str,
    external_message_id: str,
    external_user_id: str,
    text: str,
) -> InboundMessage:
    return InboundMessage(
        channel="simulated",
        channel_account_id=channel_account_id,
        channel_integration_id=channel_integration_id,
        external_message_id=external_message_id,
        external_user_id=external_user_id,
        text=text,
        occurred_at=T_START,
    )


async def seed_investigation_fixture(engine: AsyncEngine) -> SeededRuns:
    conversations = SqlAlchemyConversationRepository(engine)
    runs = SqlAlchemyAgentRunRepository(engine)

    received_a = await conversations.receive(
        TENANT_A_CTX,
        _inbound(
            channel_integration_id=CHANNEL_A,
            channel_account_id="acct-a",
            external_message_id="ext-a-1",
            external_user_id="user-pii-30111222",
            text=MESSAGE_BODY,
        ),
    )
    run_a = await runs.start(
        TENANT_A_CTX,
        received_a.conversation.id,
        received_a.message.id,
        skill="appointments",
        model_provider="fake",
        model_name="fake-llm",
    )
    await runs.finish(
        TENANT_A_CTX,
        run_a.id,
        "succeeded",
        usage={
            "input_tokens": 10,
            "output_tokens": 20,
            "prompt": PROMPT,
        },
    )

    received_b = await conversations.receive(
        TENANT_B_CTX,
        _inbound(
            channel_integration_id=CHANNEL_B,
            channel_account_id="acct-b",
            external_message_id="ext-b-1",
            external_user_id="user-b",
            text="turno tenant b secreto",
        ),
    )
    run_b = await runs.start(
        TENANT_B_CTX,
        received_b.conversation.id,
        received_b.message.id,
        skill="faq",
    )
    await runs.finish(TENANT_B_CTX, run_b.id, "succeeded")

    received_sparse = await conversations.receive(
        TENANT_A_CTX,
        _inbound(
            channel_integration_id=CHANNEL_A,
            channel_account_id="acct-a",
            external_message_id="ext-a-sparse",
            external_user_id="user-sparse",
            text="hola",
        ),
    )
    sparse = await runs.start(
        TENANT_A_CTX,
        received_sparse.conversation.id,
        received_sparse.message.id,
        skill="faq",
    )
    await runs.finish(TENANT_A_CTX, sparse.id, "succeeded")

    received_later = await conversations.receive(
        TENANT_A_CTX,
        _inbound(
            channel_integration_id=CHANNEL_A,
            channel_account_id="acct-a",
            external_message_id="ext-a-later",
            external_user_id="user-pii-30111222",
            text="seguimiento",
        ),
    )
    later_run = await runs.start(
        TENANT_A_CTX,
        received_later.conversation.id,
        received_later.message.id,
        skill="appointments",
    )
    await runs.finish(TENANT_A_CTX, later_run.id, "handed_off")

    received_inflight = await conversations.receive(
        INFLIGHT_CTX,
        _inbound(
            channel_integration_id=CHANNEL_A,
            channel_account_id="acct-a",
            external_message_id="ext-a-inflight",
            external_user_id="user-inflight",
            text="en curso",
        ),
    )
    inflight_run = await runs.start(
        INFLIGHT_CTX,
        received_inflight.conversation.id,
        received_inflight.message.id,
        skill="appointments",
    )

    workflow_id = uuid4()
    document_id = uuid4()
    async with engine.begin() as connection:
        await connection.execute(
            update(agent_run_table)
            .where(
                agent_run_table.c.tenant_id == TENANT_A,
                agent_run_table.c.id == run_a.id,
            )
            .values(
                workflow_type="create_appointment",
                mcp_server_id="mcp-appointments",
                started_at=T_START,
                finished_at=T_FINISH,
            )
        )
        await connection.execute(
            update(agent_run_table)
            .where(
                agent_run_table.c.tenant_id == TENANT_A,
                agent_run_table.c.id == later_run.id,
            )
            .values(started_at=T_LATER_START, finished_at=T_LATER_FINISH)
        )
        await connection.execute(
            update(agent_run_table)
            .where(
                agent_run_table.c.tenant_id == TENANT_A,
                agent_run_table.c.id == inflight_run.id,
            )
            .values(started_at=T_INFLIGHT, finished_at=None, status="started")
        )
        await connection.execute(
            knowledge_document_table.insert().values(
                tenant_id=TENANT_A,
                id=document_id,
                logical_name="hours.pdf",
                object_key="a/hours.pdf",
                mime_type="application/pdf",
                checksum="a" * 64,
                created_at=T_START,
            )
        )
        await connection.execute(
            knowledge_document_version_table.insert().values(
                tenant_id=TENANT_A,
                document_id=document_id,
                version=1,
                status="published",
                error_code=None,
                created_at=T_START,
                published_at=T_START,
            )
        )
        await connection.execute(
            knowledge_chunk_table.insert().values(
                tenant_id=TENANT_A,
                id=uuid4(),
                document_id=document_id,
                version=1,
                page=1,
                position=0,
                text=CHUNK_TEXT,
                embedding=[0.1, 0.2],
                source_id=SOURCE_ID,
                token_count=12,
            )
        )
        await connection.execute(
            workflow_execution_table.insert().values(
                tenant_id=TENANT_A,
                id=workflow_id,
                conversation_id=received_a.conversation.id,
                type="create_appointment",
                schema_version=1,
                state="awaiting_confirmation",
                status="running",
                data={"patient": PATIENT_REF, "dni": "30111222"},
                idempotency_key_hash=None,
                lock_version=3,
                created_at=T_START,
                updated_at=T_ADVANCE,
                error=WORKFLOW_ERROR,
            )
        )
        await connection.execute(
            workflow_transition_table.insert(),
            [
                {
                    "tenant_id": TENANT_A,
                    "workflow_id": workflow_id,
                    "sequence": 1,
                    "from_state": None,
                    "to_state": "collecting",
                    "command_id": "cmd-search",
                    "event_type": "knowledge.search",
                    "payload": {
                        "source_ids": [SOURCE_ID],
                        "source_count": 1,
                        "chunk": CHUNK_TEXT,
                    },
                    "actor": "system",
                    "run_id": run_a.id,
                    "timestamp": T_SEARCH,
                },
                {
                    "tenant_id": TENANT_A,
                    "workflow_id": workflow_id,
                    "sequence": 2,
                    "from_state": "collecting",
                    "to_state": "collecting",
                    "command_id": "cmd-tool-1",
                    "event_type": "tool.execute",
                    "payload": {
                        "tool_name": "appointments.search",
                        "mcp_server_id": "mcp-appointments",
                        "status": "ok",
                        "retry_count": 0,
                        "arguments": TOOL_ARGUMENTS,
                    },
                    "actor": "system",
                    "run_id": run_a.id,
                    "timestamp": T_TOOL,
                },
                {
                    "tenant_id": TENANT_A,
                    "workflow_id": workflow_id,
                    "sequence": 3,
                    "from_state": "collecting",
                    "to_state": "collecting",
                    "command_id": "cmd-retry",
                    "event_type": "retry",
                    "payload": {"attempt": 2},
                    "actor": "system",
                    "run_id": run_a.id,
                    "timestamp": T_RETRY,
                },
                {
                    "tenant_id": TENANT_A,
                    "workflow_id": workflow_id,
                    "sequence": 4,
                    "from_state": "collecting",
                    "to_state": "executing",
                    "command_id": "cmd-tool-2",
                    "event_type": "tool.execute",
                    "payload": {
                        "tool_name": "appointments.create",
                        "mcp_server_id": "mcp-appointments",
                        "status": "ok",
                        "retry_count": 1,
                    },
                    "actor": "system",
                    "run_id": run_a.id,
                    "timestamp": T_TOOL2,
                },
                {
                    "tenant_id": TENANT_A,
                    "workflow_id": workflow_id,
                    "sequence": 5,
                    "from_state": "executing",
                    "to_state": "awaiting_confirmation",
                    "command_id": "cmd-advance",
                    "event_type": "workflow.advance",
                    "payload": {"prompt": PROMPT, "patient": PATIENT_REF},
                    "actor": "system",
                    "run_id": run_a.id,
                    "timestamp": T_ADVANCE,
                },
            ],
        )
        await connection.execute(
            handoff_table.insert().values(
                tenant_id=TENANT_A,
                id=uuid4(),
                conversation_id=received_a.conversation.id,
                workflow_id=workflow_id,
                reason="manual_review_required",
                summary={
                    "patient_reference": PATIENT_REF,
                    "reason": "manual_review_required",
                    "collected_fields": {"dni": "30111222"},
                    "completed_actions": ["search"],
                    "active_workflow_id": str(workflow_id),
                    "notes": MESSAGE_BODY,
                },
                business_key=f"handoff:{run_a.id}",
                status="requested",
                external_case_reference="case-opaque-1",
                owner_reference=None,
                requested_at=T_HANDOFF,
                accepted_at=None,
                resolved_at=None,
            )
        )
        await connection.execute(
            scheduled_job_table.insert(),
            [
                {
                    "tenant_id": TENANT_A,
                    "id": uuid4(),
                    "type": "appointment_reminder",
                    "payload": {
                        "appointment_id": "apt-1",
                        "correlation_id": str(CORR_A),
                        "telemetry": {"correlation_id": str(CORR_A)},
                        "patient": PATIENT_REF,
                    },
                    "business_key": "apt-1:pre_appointment",
                    "scheduled_for": T_JOB,
                    "schedule_version": 1,
                    "status": "pending",
                    "attempts": 2,
                    "lock_owner": None,
                    "lock_expires_at": None,
                    "last_error": JOB_LAST_ERROR,
                    "created_at": T_JOB,
                    "updated_at": T_JOB,
                },
                {
                    "tenant_id": TENANT_A,
                    "id": uuid4(),
                    "type": "appointment_reminder",
                    "payload": {
                        "appointment_id": "apt-other",
                        "correlation_id": str(uuid4()),
                    },
                    "business_key": "apt-other:pre_appointment",
                    "scheduled_for": T_JOB,
                    "schedule_version": 1,
                    "status": "pending",
                    "attempts": 0,
                    "lock_owner": None,
                    "lock_expires_at": None,
                    "last_error": None,
                    "created_at": T_JOB,
                    "updated_at": T_JOB,
                },
            ],
        )
        await connection.execute(
            audit_event_table.insert(),
            [
                {
                    "id": uuid4(),
                    "tenant_id": TENANT_A,
                    "actor_id": ACTOR_A,
                    "action": "tool_completed",
                    "version": 1,
                    "created_at": T_AUDIT_1,
                },
                {
                    "id": uuid4(),
                    "tenant_id": TENANT_A,
                    "actor_id": ACTOR_A,
                    "action": "workflow_transition",
                    "version": 1,
                    "created_at": T_AUDIT_2,
                },
                {
                    "id": uuid4(),
                    "tenant_id": TENANT_A,
                    "actor_id": ACTOR_A,
                    "action": "job_scheduled",
                    "version": 1,
                    "created_at": T_AUDIT_3,
                },
                {
                    "id": uuid4(),
                    "tenant_id": TENANT_B,
                    "actor_id": ACTOR_A,
                    "action": "tenant_b_only",
                    "version": 1,
                    "created_at": T_AUDIT_2,
                },
            ],
        )
        await connection.execute(
            conversation_table.insert().values(
                id=received_a.conversation.id,
                tenant_id=TENANT_B,
                channel_integration_id=CHANNEL_B,
                external_user_ref="twin-a-conversation",
                status="closed",
                last_message_at=datetime(2099, 1, 1, tzinfo=UTC),
                lock_version=1,
            )
        )
        await connection.execute(
            message_table.insert().values(
                id=received_a.message.id,
                tenant_id=TENANT_B,
                conversation_id=received_a.conversation.id,
                channel_integration_id=CHANNEL_B,
                direction="outbound",
                external_message_id="twin-a-message",
                content="tenant b twin body",
                content_type="document",
                occurred_at=T_START,
                received_at=T_START,
                dedupe_hash="b" * 64,
            )
        )
        await connection.execute(
            workflow_execution_table.insert().values(
                tenant_id=TENANT_B,
                id=workflow_id,
                conversation_id=received_a.conversation.id,
                type=TENANT_B_WORKFLOW_TYPE,
                schema_version=1,
                state="failed",
                status="failed",
                data={},
                idempotency_key_hash=None,
                lock_version=1,
                created_at=T_START,
                updated_at=T_START,
                error=None,
            )
        )
        await connection.execute(
            workflow_transition_table.insert().values(
                tenant_id=TENANT_B,
                workflow_id=workflow_id,
                sequence=1,
                from_state=None,
                to_state="failed",
                command_id="cmd-b-twin",
                event_type="tool.execute",
                payload={
                    "tool_name": TENANT_B_TOOL,
                    "mcp_server_id": "mcp-b",
                    "status": "ok",
                    "retry_count": 0,
                },
                actor="system",
                run_id=run_a.id,
                timestamp=T_TOOL,
            )
        )
        await connection.execute(
            handoff_table.insert().values(
                tenant_id=TENANT_B,
                id=uuid4(),
                conversation_id=received_a.conversation.id,
                workflow_id=workflow_id,
                reason="out_of_scope",
                summary={"reason": "out_of_scope"},
                business_key="handoff:twin-b",
                status="requested",
                external_case_reference=None,
                owner_reference=None,
                requested_at=T_B_HANDOFF,
                accepted_at=None,
                resolved_at=None,
            )
        )
        await connection.execute(
            scheduled_job_table.insert().values(
                tenant_id=TENANT_B,
                id=uuid4(),
                type="appointment_reminder",
                payload={
                    "appointment_id": "apt-b-twin",
                    "correlation_id": str(CORR_A),
                    "telemetry": {"correlation_id": str(CORR_A)},
                },
                business_key="apt-b-twin:pre_appointment",
                scheduled_for=T_JOB,
                schedule_version=1,
                status="pending",
                attempts=99,
                lock_owner=None,
                lock_expires_at=None,
                last_error=TENANT_B_JOB_MARKER,
                created_at=T_JOB,
                updated_at=T_JOB,
            )
        )
        await connection.execute(
            handoff_table.insert().values(
                tenant_id=TENANT_A,
                id=uuid4(),
                conversation_id=received_a.conversation.id,
                workflow_id=None,
                reason=LATER_HANDOFF_REASON,
                summary={"reason": LATER_HANDOFF_REASON},
                business_key=f"handoff:{later_run.id}",
                status="requested",
                external_case_reference=None,
                owner_reference=None,
                requested_at=T_LATER_HANDOFF,
                accepted_at=None,
                resolved_at=None,
            )
        )
        await connection.execute(
            scheduled_job_table.insert().values(
                tenant_id=TENANT_A,
                id=uuid4(),
                type="appointment_reminder",
                payload={
                    "appointment_id": "apt-inflight",
                    "correlation_id": str(CORR_INFLIGHT),
                    "telemetry": {"correlation_id": str(CORR_INFLIGHT)},
                },
                business_key="apt-inflight:pre_appointment",
                scheduled_for=T_INFLIGHT_JOB,
                schedule_version=1,
                status="pending",
                attempts=1,
                lock_owner=None,
                lock_expires_at=None,
                last_error=None,
                created_at=T_INFLIGHT_JOB,
                updated_at=T_INFLIGHT_JOB,
            )
        )
        await connection.execute(
            audit_event_table.insert().values(
                id=uuid4(),
                tenant_id=TENANT_A,
                actor_id=ACTOR_A,
                action="inflight_audit",
                version=1,
                created_at=T_INFLIGHT_JOB,
            )
        )

    return SeededRuns(
        run_a_id=run_a.id,
        run_b_id=run_b.id,
        sparse_run_id=sparse.id,
        later_run_id=later_run.id,
        inflight_run_id=inflight_run.id,
        trigger_message_id=received_a.message.id,
    )


@pytest.fixture
async def seeded() -> AsyncIterator[
    tuple[SqlAlchemyRunInvestigationQuery, SeededRuns, AsyncEngine]
]:
    _reset_schema()
    _seed_tenants_and_channels()
    engine = create_async_engine(DATABASE_URL)
    try:
        runs = await seed_investigation_fixture(engine)
        yield SqlAlchemyRunInvestigationQuery(engine), runs, engine
    finally:
        await engine.dispose()


@pytest.mark.anyio
@pytest.mark.integration
async def test_run_query_rejects_cross_tenant(
    seeded: tuple[SqlAlchemyRunInvestigationQuery, SeededRuns, AsyncEngine],
) -> None:
    query, runs, _engine = seeded
    with pytest.raises(RunNotFound):
        await query.get(TENANT_A_CTX, runs.run_b_id)


@pytest.mark.anyio
@pytest.mark.integration
async def test_missing_and_cross_tenant_are_uniform_not_found(
    seeded: tuple[SqlAlchemyRunInvestigationQuery, SeededRuns, AsyncEngine],
) -> None:
    query, runs, _engine = seeded
    missing_id = uuid4()
    with pytest.raises(RunNotFound) as missing:
        await query.get(TENANT_A_CTX, missing_id)
    with pytest.raises(RunNotFound) as cross:
        await query.get(TENANT_A_CTX, runs.run_b_id)
    assert missing.value.safe_message == cross.value.safe_message
    assert missing.value.safe_message == "Resource not found"
    assert missing.value.code == "not_found"
    assert cross.value.code == "not_found"


@pytest.mark.anyio
@pytest.mark.integration
async def test_complete_run_reconstructs_config_skill_workflow_mcp_tools(
    seeded: tuple[SqlAlchemyRunInvestigationQuery, SeededRuns, AsyncEngine],
) -> None:
    query, runs, _engine = seeded
    investigation = await query.get(TENANT_A_CTX, runs.run_a_id)
    assert investigation.run.id == runs.run_a_id
    assert investigation.run.config_version == 1
    assert investigation.run.skill == "appointments"
    assert investigation.run.workflow_type == "create_appointment"
    assert investigation.run.mcp_server_id == "mcp-appointments"
    assert investigation.run.status == "succeeded"
    assert investigation.run.input_tokens == 10
    assert investigation.run.output_tokens == 20
    assert investigation.workflow is not None
    assert investigation.workflow.type == "create_appointment"
    assert investigation.workflow.state == "awaiting_confirmation"
    tool_names = {item.tool_name for item in investigation.tools}
    assert tool_names == {"appointments.search", "appointments.create"}
    assert investigation.retrievals[0].source_id == SOURCE_ID
    assert investigation.handoff is not None
    assert investigation.handoff.reason == "manual_review_required"
    assert len(investigation.jobs) == 1
    assert investigation.jobs[0].attempts == 2
    assert investigation.conversation.id == investigation.run.conversation_id
    assert investigation.conversation.trigger_message_id == runs.trigger_message_id
    assert investigation.conversation.trigger_direction == "inbound"


@pytest.mark.anyio
@pytest.mark.integration
async def test_timeline_orders_transitions_retries_and_jobs_in_utc(
    seeded: tuple[SqlAlchemyRunInvestigationQuery, SeededRuns, AsyncEngine],
) -> None:
    query, runs, _engine = seeded
    investigation = await query.get(TENANT_A_CTX, runs.run_a_id)
    occurred = [event.occurred_at for event in investigation.timeline]
    assert occurred == sorted(occurred)
    assert all(event.occurred_at.tzinfo is not None for event in investigation.timeline)
    assert all(event.occurred_at.utcoffset() == timedelta(0) for event in investigation.timeline)
    kinds = {event.kind for event in investigation.timeline}
    assert "transition" in kinds
    assert "retry" in kinds
    assert "job" in kinds
    assert "tool" in kinds


@pytest.mark.anyio
@pytest.mark.integration
async def test_sparse_run_allows_missing_optional_refs(
    seeded: tuple[SqlAlchemyRunInvestigationQuery, SeededRuns, AsyncEngine],
) -> None:
    query, runs, _engine = seeded
    investigation = await query.get(TENANT_A_CTX, runs.sparse_run_id)
    assert investigation.run.id == runs.sparse_run_id
    assert investigation.workflow is None
    assert investigation.handoff is None
    assert investigation.tools == ()
    assert investigation.jobs == ()
    assert investigation.retrievals == ()


@pytest.mark.anyio
@pytest.mark.integration
async def test_tools_and_audit_events_paginate(
    seeded: tuple[SqlAlchemyRunInvestigationQuery, SeededRuns, AsyncEngine],
) -> None:
    query, runs, _engine = seeded
    first = await query.get(
        TENANT_A_CTX,
        runs.run_a_id,
        tools_limit=1,
        events_limit=1,
    )
    assert len(first.tools) == 1
    assert first.tools_next_cursor is not None
    assert len(first.audit_events) == 1
    assert first.audit_next_cursor is not None
    second_tools = await query.get(
        TENANT_A_CTX,
        runs.run_a_id,
        tools_cursor=first.tools_next_cursor,
        tools_limit=1,
    )
    assert len(second_tools.tools) == 1
    assert second_tools.tools[0].tool_name != first.tools[0].tool_name
    second_events = await query.get(
        TENANT_A_CTX,
        runs.run_a_id,
        events_cursor=first.audit_next_cursor,
        events_limit=1,
    )
    assert len(second_events.audit_events) == 1
    assert second_events.audit_events[0].id != first.audit_events[0].id


@pytest.mark.anyio
@pytest.mark.integration
async def test_summaries_omit_bodies_chunks_prompts_payloads_and_patient_ids(
    seeded: tuple[SqlAlchemyRunInvestigationQuery, SeededRuns, AsyncEngine],
) -> None:
    query, runs, _engine = seeded
    investigation = await query.get(TENANT_A_CTX, runs.run_a_id)
    dumped = investigation.model_dump_json()
    assert MESSAGE_BODY not in dumped
    assert CHUNK_TEXT not in dumped
    assert PROMPT not in dumped
    assert PATIENT_REF not in dumped
    assert "30111222" not in dumped
    assert "patient@example.com" not in dumped
    assert "secret-token" not in dumped
    assert "sk-live-secret" not in dumped
    assert "user-pii-30111222" not in dumped
    assert "turno tenant b secreto" not in dumped
    assert "arguments" not in dumped
    assert investigation.handoff is not None
    dumped_handoff = investigation.handoff.model_dump()
    assert "patient_reference" not in dumped_handoff
    assert "notes" not in dumped_handoff
    assert "collected_fields" not in dumped_handoff
    assert investigation.workflow is not None
    assert investigation.workflow.error is not None
    assert "[EMAIL]" in investigation.workflow.error
    assert "Bearer [REDACTED]" in investigation.workflow.error
    assert "patient@example.com" not in investigation.workflow.error
    assert "secret-token" not in investigation.workflow.error
    assert "Juan Perez" in investigation.workflow.error
    assert investigation.jobs[0].last_error is not None
    assert "[EMAIL]" in investigation.jobs[0].last_error
    assert "Bearer [REDACTED]" in investigation.jobs[0].last_error
    assert "Juan Perez" in investigation.jobs[0].last_error


@pytest.mark.anyio
@pytest.mark.integration
async def test_authorized_query_is_audited(
    seeded: tuple[SqlAlchemyRunInvestigationQuery, SeededRuns, AsyncEngine],
) -> None:
    query, runs, engine = seeded
    await query.get(TENANT_A_CTX, runs.run_a_id)
    async with engine.connect() as connection:
        actions = (
            await connection.execute(
                select(audit_event_table.c.action).where(
                    audit_event_table.c.tenant_id == TENANT_A,
                    audit_event_table.c.action == AUDIT_INVESTIGATION_ACTION,
                )
            )
        ).scalars().all()
    assert AUDIT_INVESTIGATION_ACTION in actions


@pytest.mark.anyio
@pytest.mark.integration
async def test_tenant_b_can_read_own_run(
    seeded: tuple[SqlAlchemyRunInvestigationQuery, SeededRuns, AsyncEngine],
) -> None:
    query, runs, _engine = seeded
    investigation = await query.get(TENANT_B_CTX, runs.run_b_id)
    assert investigation.run.id == runs.run_b_id
    assert investigation.run.skill == "faq"


@pytest.mark.anyio
@pytest.mark.integration
async def test_earlier_run_does_not_surface_later_conversation_handoff(
    seeded: tuple[SqlAlchemyRunInvestigationQuery, SeededRuns, AsyncEngine],
) -> None:
    query, runs, _engine = seeded
    earlier = await query.get(TENANT_A_CTX, runs.run_a_id)
    later = await query.get(TENANT_A_CTX, runs.later_run_id)
    assert earlier.handoff is not None
    assert earlier.handoff.reason == "manual_review_required"
    assert later.handoff is not None
    assert later.handoff.reason == LATER_HANDOFF_REASON
    assert earlier.handoff.id != later.handoff.id


@pytest.mark.anyio
@pytest.mark.integration
async def test_tenant_predicates_exclude_cross_tenant_twins(
    seeded: tuple[SqlAlchemyRunInvestigationQuery, SeededRuns, AsyncEngine],
) -> None:
    query, runs, _engine = seeded
    investigation = await query.get(TENANT_A_CTX, runs.run_a_id)
    assert investigation.conversation.status != "closed"
    assert investigation.conversation.trigger_direction == "inbound"
    assert investigation.conversation.trigger_content_type == "text"
    assert investigation.workflow is not None
    assert investigation.workflow.type != TENANT_B_WORKFLOW_TYPE
    assert TENANT_B_TOOL not in {item.tool_name for item in investigation.tools}
    assert investigation.handoff is not None
    assert investigation.handoff.reason != "out_of_scope"
    assert all(
        TENANT_B_JOB_MARKER not in (item.last_error or "")
        for item in investigation.jobs
    )
    assert "tenant_b_only" not in {item.action for item in investigation.audit_events}


@pytest.mark.anyio
@pytest.mark.integration
async def test_inflight_run_keeps_open_ended_job_and_audit_window(
    seeded: tuple[SqlAlchemyRunInvestigationQuery, SeededRuns, AsyncEngine],
) -> None:
    query, runs, _engine = seeded
    investigation = await query.get(TENANT_A_CTX, runs.inflight_run_id)
    assert investigation.run.finished_at is None
    assert len(investigation.jobs) == 1
    assert "inflight_audit" in {item.action for item in investigation.audit_events}


@pytest.mark.anyio
@pytest.mark.integration
async def test_malformed_cursor_fails_closed(
    seeded: tuple[SqlAlchemyRunInvestigationQuery, SeededRuns, AsyncEngine],
) -> None:
    query, runs, _engine = seeded
    with pytest.raises(InvalidCursor) as tools_exc:
        await query.get(TENANT_A_CTX, runs.run_a_id, tools_cursor="not-a-cursor")
    with pytest.raises(InvalidCursor) as events_exc:
        await query.get(TENANT_A_CTX, runs.run_a_id, events_cursor="also-bad")
    assert tools_exc.value.code == "validation_error"
    assert events_exc.value.code == "validation_error"
