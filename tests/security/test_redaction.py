"""Secret and PII redaction across stores, summaries and audit surfaces.

Canaries come from `tests/fixtures/security_matrix.py`. No test may assert on a
real credential, and no canary may survive in a store, outbox, audit summary or
error payload.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine

from ia_mcp.configuration.models import AgentConfig, AppointmentPolicy, TenantConfig
from ia_mcp.conversation.adapters.sqlalchemy import SqlAlchemyConversationRepository
from ia_mcp.conversation.models import InboundMessage
from ia_mcp.handoff.adapters.fake import FakeHandoffAdapter
from ia_mcp.handoff.models import HandoffRequest
from ia_mcp.handoff.service import (
    HandoffService,
    SqlAlchemyHandoffRepository,
    handoff_table,
)
from ia_mcp.mcp.audit import ToolAuditAdapter, sanitize_summary
from ia_mcp.mcp.executor import ToolCall, ToolExecutor
from ia_mcp.observability.redaction import redact
from ia_mcp.workflows.adapters.sqlalchemy import (
    SqlAlchemyWorkflowRepository,
    outbox_event_table,
    workflow_transition_table,
)
from ia_mcp.workflows.appointments.create import CreateAppointmentDefinition
from ia_mcp.workflows.engine import WorkflowEngine
from ia_mcp.workflows.models import AdvanceCommand
from tests.fixtures.security_matrix import (
    ALL_TOOLS,
    AUTHORIZATION_HEADER,
    CANARY_A_BOOKING_TOKEN,
    CHANNEL_A,
    CONNECTION_STRING,
    COOKIE_HEADER,
    DATABASE_URL,
    OCCURRED_AT,
    PII_DOCUMENT,
    PII_DOCUMENT_DIGITS,
    PII_EMAIL,
    PII_PHONE,
    SECRET_VALUE,
    SSRF_ENDPOINT,
    TENANT_A,
    TENANT_A_CTX,
    reset_schema,
    seed_tenants_and_channels,
    two_tenant_capability,
)

SECRET_CANARIES = (
    SECRET_VALUE,
    "s3cr3t-db-pass",
    "canary-access-token",
    "canary-session",
    PII_EMAIL,
    PII_DOCUMENT_DIGITS,
    "5555-4444",
)


@pytest.mark.security
def test_redactor_removes_credentials_pii_and_connection_strings() -> None:
    # The single bearer/email contract established in P02 must keep holding.
    assert redact("Bearer secret-token for patient@example.com") == (
        "Bearer [REDACTED] for [EMAIL]"
    )
    payload = ", ".join(
        (
            AUTHORIZATION_HEADER,
            COOKIE_HEADER,
            CONNECTION_STRING,
            f"api_key={SECRET_VALUE}",
            f'"client_secret": "{SECRET_VALUE}"',
            f"password={SECRET_VALUE}",
            PII_DOCUMENT,
            f"telefono {PII_PHONE}",
            PII_EMAIL,
        )
    )
    redacted = redact(payload)
    for canary in SECRET_CANARIES:
        assert canary not in redacted, canary
    assert "s3cr3t" not in redacted
    assert "admin:" not in redacted
    assert "[REDACTED]" in redacted
    assert "[EMAIL]" in redacted
    # Non-sensitive content survives so operators keep usable context.
    assert redact("specialty=cardiologia") == "specialty=cardiologia"
    assert "cardiologia" in redact("specialty=cardiologia and api_key=abc")


@pytest.mark.anyio
@pytest.mark.security
async def test_handoff_summary_and_outbox_redact_pii_and_secrets() -> None:
    reset_schema()
    seed_tenants_and_channels()
    engine = create_async_engine(DATABASE_URL)
    try:
        conversations = SqlAlchemyConversationRepository(engine)
        received = await conversations.receive(
            TENANT_A_CTX,
            InboundMessage(
                channel="simulated",
                channel_account_id="acct-a",
                channel_integration_id=CHANNEL_A,
                external_message_id="ext-redaction-a",
                external_user_id="user-a",
                text="quiero hablar con una persona",
                occurred_at=OCCURRED_AT,
            ),
        )
        provider = FakeHandoffAdapter()
        service = HandoffService(SqlAlchemyHandoffRepository(engine), provider)
        result = await service.create(
            TENANT_A_CTX,
            HandoffRequest(
                conversation_id=received.conversation.id,
                reason="explicit_request",
                business_key=f"handoff:{received.conversation.id}",
                patient_reference=PII_EMAIL,
                collected_fields={
                    "specialty": "cardiologia",
                    "password": SECRET_VALUE,
                    "api_token": SECRET_VALUE,
                    "contact": PII_EMAIL,
                },
                notes=(
                    f"{PII_DOCUMENT}, telefono {PII_PHONE}, "
                    f"{AUTHORIZATION_HEADER}, {COOKIE_HEADER}, {CONNECTION_STRING}"
                ),
            ),
        )
        summary_blob = str(result.summary.as_payload())
        delivered = provider.cases_for(TENANT_A_CTX)
        assert len(delivered) == 1
        delivered_blob = str(delivered[0].summary.as_payload())
        async with engine.connect() as connection:
            stored = (
                await connection.execute(
                    select(handoff_table.c.summary).where(
                        handoff_table.c.tenant_id == TENANT_A
                    )
                )
            ).scalars().all()
            outbox = (
                await connection.execute(
                    select(outbox_event_table.c.payload).where(
                        outbox_event_table.c.tenant_id == TENANT_A
                    )
                )
            ).scalars().all()
        blobs = (
            summary_blob,
            delivered_blob,
            str(stored),
            str(outbox),
        )
        for blob in blobs:
            for canary in SECRET_CANARIES:
                assert canary not in blob, canary
            assert "password" not in blob
            assert "api_token" not in blob
        assert result.summary.collected_fields["specialty"] == "cardiologia"
        assert "[EMAIL]" in (result.summary.patient_reference or "")
    finally:
        await engine.dispose()


@pytest.mark.anyio
@pytest.mark.security
async def test_workflow_payload_and_presented_slots_drop_secret_material() -> None:
    reset_schema()
    seed_tenants_and_channels()
    engine = create_async_engine(DATABASE_URL)
    try:
        repository = SqlAlchemyWorkflowRepository(engine)
        definition = CreateAppointmentDefinition()
        workflows = WorkflowEngine(repository, definition)
        capability = two_tenant_capability(id_factory="appt-a-1")
        executor = ToolExecutor(
            server=ALL_TOOLS,
            tenant=ALL_TOOLS,
            skill=ALL_TOOLS,
            capability=capability,
        )
        config = TenantConfig(
            tenant_id=TENANT_A,
            version=1,
            agent=AgentConfig(tone="cordial"),
            enabled_skills=frozenset({"appointments"}),
            appointments=AppointmentPolicy(
                required_fields=("specialty", "date_from", "date_to")
            ),
        )
        started = await definition.start(
            workflows, TENANT_A_CTX, command_id="start-redaction", config=config
        )
        await definition.collect_fields(
            workflows,
            TENANT_A_CTX,
            started.workflow_id,
            command_id="collect-redaction",
            fields={
                "specialty": "cardiologia",
                "date_from": "2026-09-03",
                "date_to": "2026-09-03",
                "booking_token": CANARY_A_BOOKING_TOKEN,
                "authorization": AUTHORIZATION_HEADER,
            },
            config=config,
        )
        presented = await definition.search_slots(
            workflows,
            executor,
            TENANT_A_CTX,
            started.workflow_id,
            command_id="search-redaction",
            run_id=uuid4(),
            config=config,
        )
        slots = presented.data.get("slots")
        assert isinstance(slots, list)
        assert slots
        assert all("booking_token" not in slot for slot in slots)
        # A caller that pushes credential material straight at the engine is
        # sanitized before the transition and the outbox are written.
        leaked = await workflows.advance(
            TENANT_A_CTX,
            AdvanceCommand(
                workflow_id=started.workflow_id,
                command_id="leak-attempt",
                event_type="select_slot",
                payload={
                    "phase": "awaiting_slot_selection",
                    "selected_slot": "slot-a-1",
                    "booking_token": CANARY_A_BOOKING_TOKEN,
                    "authorization": AUTHORIZATION_HEADER,
                    "password": SECRET_VALUE,
                    "mcp_credential": CONNECTION_STRING,
                },
            ),
        )
        assert leaked.data.get("selected_slot") == "slot-a-1"
        async with engine.connect() as connection:
            payloads = (
                await connection.execute(
                    select(workflow_transition_table.c.payload).where(
                        workflow_transition_table.c.tenant_id == TENANT_A
                    )
                )
            ).scalars().all()
            outbox = (
                await connection.execute(
                    select(outbox_event_table.c.payload).where(
                        outbox_event_table.c.tenant_id == TENANT_A
                    )
                )
            ).scalars().all()
        for blob in (
            str(presented.data),
            str(leaked.data),
            str(payloads),
            str(outbox),
        ):
            assert CANARY_A_BOOKING_TOKEN not in blob
            assert "booking_token" not in blob
            assert "canary-access-token" not in blob
            assert "authorization" not in blob
            assert SECRET_VALUE not in blob
            assert "s3cr3t-db-pass" not in blob
        assert "cardiologia" in str(presented.data)
    finally:
        await engine.dispose()


@pytest.mark.anyio
@pytest.mark.security
async def test_tool_audit_summary_omits_secret_values_and_endpoint() -> None:
    capability = two_tenant_capability(id_factory="appt-a-1")
    adapter = ToolAuditAdapter()
    executor = ToolExecutor(
        server=ALL_TOOLS,
        tenant=ALL_TOOLS,
        skill=ALL_TOOLS,
        capability=capability,
        audit_hook=adapter,
    )
    await executor.execute(
        TENANT_A_CTX,
        uuid4(),
        ToolCall(
            name="appointments.create",
            arguments={
                "slot_id": "slot-a-1",
                "booking_token": CANARY_A_BOOKING_TOKEN,
                "patient": {
                    "name": "Ada Lovelace",
                    "email": PII_EMAIL,
                    "document_number": PII_DOCUMENT_DIGITS,
                },
            },
            idempotency_key="k-audit-1",
        ),
    )
    assert len(adapter.executions) == 1
    execution = adapter.executions[0]
    assert execution.tenant_id == TENANT_A
    assert execution.tool == "appointments.create"
    blob = repr(execution)
    for canary in (
        CANARY_A_BOOKING_TOKEN,
        PII_EMAIL,
        PII_DOCUMENT_DIGITS,
        "Ada Lovelace",
        SSRF_ENDPOINT,
    ):
        assert canary not in blob, canary
    lowered = blob.lower()
    assert "endpoint" not in lowered
    assert "auth_reference" not in lowered
    assert "credentials" not in lowered
    # The sanitizer keeps safe metadata, drops sensitive keys, and fails closed
    # on a whole subtree as soon as any value inside it looks like a credential.
    cleaned = sanitize_summary(
        {
            "tool": "appointments.create",
            "booking_token": CANARY_A_BOOKING_TOKEN,
            "safe": {"specialty": "cardiologia"},
            "tainted": {"header": AUTHORIZATION_HEADER, "specialty": "cardiologia"},
        }
    )
    assert cleaned["tool"] == "appointments.create"
    assert "booking_token" not in cleaned
    assert cleaned["safe"] == {"specialty": "cardiologia"}
    assert "tainted" not in cleaned
