"""Shared canaries, tenant contexts and threat matrix for the security suite.

The matrix rows below are the executable form of the threat table in
`docs/01-architecture/security-and-multitenancy.md`. Every AC-P06-006 isolation
leg (config, knowledge, secret, tool, state, job, audit) must be claimed by at
least one row, and `tests/security/test_tenant_isolation.py` enforces that the
referenced test really exists.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from alembic.config import Config
from pydantic import SecretStr
from sqlalchemy import create_engine, text

from alembic import command
from ia_mcp.configuration.adapters.sqlalchemy import (
    channel_integration_table,
    tenant_table,
)
from ia_mcp.configuration.models import (
    AgentConfig,
    AppointmentPolicy,
    McpConfig,
    TenantAdminContext,
    TenantConfig,
    TenantConfigDraft,
)
from ia_mcp.contracts.appointments import AppointmentSlot
from ia_mcp.mcp.fakes.appointments import FakeAppointmentCapability
from ia_mcp.tenancy.models import TenantContext, TenantIdentity

ROOT = Path(__file__).resolve().parents[2]
DATABASE_URL = "postgresql+psycopg://francojimenez@127.0.0.1:5432/ia_mcp_p02_t03"

TENANT_A = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
TENANT_B = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
CHANNEL_A = UUID("aa111111-1111-1111-1111-111111111111")
CHANNEL_B = UUID("bb111111-1111-1111-1111-111111111111")

TENANT_A_IDENTITY = TenantIdentity(tenant_id=TENANT_A, tenant_slug="tenant-a")
TENANT_B_IDENTITY = TenantIdentity(tenant_id=TENANT_B, tenant_slug="tenant-b")

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

TENANT_A_ADMIN_CTX = TenantAdminContext(
    identity=TENANT_A_IDENTITY,
    principal_id=UUID("11111111-1111-1111-1111-111111111111"),
    roles=frozenset({"tenant_admin"}),
    correlation_id=UUID("55555555-5555-5555-5555-555555555555"),
)
TENANT_B_ADMIN_CTX = TenantAdminContext(
    identity=TENANT_B_IDENTITY,
    principal_id=UUID("22222222-2222-2222-2222-222222222222"),
    roles=frozenset({"tenant_admin"}),
    correlation_id=UUID("66666666-6666-6666-6666-666666666666"),
)

BA = ZoneInfo("America/Argentina/Buenos_Aires")
OCCURRED_AT = datetime(2026, 8, 28, 4, 20, tzinfo=UTC)
CAPABILITY_CLOCK = datetime(2026, 8, 28, 12, 0, tzinfo=BA)
SLOT_STARTS_AT = datetime(2026, 9, 3, 12, 0, tzinfo=BA)
SLOT_ENDS_AT = datetime(2026, 9, 3, 12, 30, tzinfo=BA)

ALL_TOOLS: frozenset[str] = frozenset(
    {
        "appointments.search",
        "appointments.get",
        "appointments.create",
        "appointments.cancel",
        "appointments.reschedule",
        "appointments.confirm",
    }
)

# Canaries. Every value is synthetic; none of them may cross a tenant boundary
# and none of the secret/PII canaries may reach a store, log, audit summary or
# handoff payload.
CANARY_A = "canary-a"
CANARY_B = "canary-b"
CANARY_B_PRACTITIONER = "Dr. Bravo Exclusive"
CANARY_B_LOCATION = "sede-norte-b"
CANARY_B_PATIENT = "Bravo Patient"
CANARY_B_BOOKING_TOKEN = "tok-b-secret"
CANARY_A_BOOKING_TOKEN = "tok-a-secret"

SECRET_REFERENCE_A = "secret://mcp/tenant-a"
SECRET_REFERENCE_B = "secret://mcp/tenant-b"
SECRET_VALUE = "sk-live-must-never-be-stored"
CONNECTION_STRING = "postgresql://admin:s3cr3t-db-pass@db.internal:5432/ia_mcp"
COOKIE_HEADER = "Cookie: session=eyJhbGciOiJIUzI1NiJ9.canary-session"
AUTHORIZATION_HEADER = "Authorization: Bearer canary-access-token"
PII_DOCUMENT = "DNI 20.345.678"
PII_DOCUMENT_DIGITS = "20.345.678"
PII_PHONE = "+54 9 11 5555-4444"
PII_EMAIL = "paciente.canario@example.com"

# Hosts the platform is allowed to reach for MCP. Anything else is SSRF.
ALLOWED_MCP_HOSTS: frozenset[str] = frozenset({"mcp.tenant-a.example"})
ALLOWED_MCP_ENDPOINT = "https://mcp.tenant-a.example/appointments"
SSRF_ENDPOINT = "https://169.254.169.254/latest/meta-data/iam/credentials"
SSRF_PLAINTEXT_ENDPOINT = "http://mcp.tenant-a.example/appointments"

ISOLATION_LEGS: frozenset[str] = frozenset(
    {"config", "knowledge", "secret", "tool", "state", "job", "audit"}
)


@dataclass(frozen=True, slots=True)
class MatrixRow:
    """One executable row of the architecture threat matrix."""

    leg: str
    threat: str
    boundary: str
    module: str
    test: str

    def __post_init__(self) -> None:
        if self.leg not in ISOLATION_LEGS:
            raise ValueError(f"unknown isolation leg: {self.leg}")


SECURITY_MATRIX: tuple[MatrixRow, ...] = (
    MatrixRow(
        leg="state",
        threat="IDOR",
        boundary="conversation/run store",
        module="tests.security.test_tenant_isolation",
        test="test_conversation_and_session_a_are_not_found_under_tenant_b",
    ),
    MatrixRow(
        leg="state",
        threat="Spoofing de tenant",
        boundary="conversation store",
        module="tests.security.test_tenant_isolation",
        test="test_tenant_b_receive_does_not_attach_to_tenant_a_conversation",
    ),
    MatrixRow(
        leg="state",
        threat="IDOR",
        boundary="workflow store",
        module="tests.security.test_tenant_isolation",
        test="test_workflow_state_of_a_is_invisible_to_tenant_b",
    ),
    MatrixRow(
        leg="state",
        threat="IDOR",
        boundary="handoff platform",
        module="tests.security.test_tenant_isolation",
        test="test_operator_of_a_does_not_receive_case_b",
    ),
    MatrixRow(
        leg="knowledge",
        threat="SQL/vector leakage",
        boundary="vector store",
        module="tests.security.test_tenant_isolation",
        test="test_search_under_a_never_returns_tenant_b_canary_chunk",
    ),
    MatrixRow(
        leg="knowledge",
        threat="IDOR",
        boundary="document lifecycle",
        module="tests.security.test_tenant_isolation",
        test="test_tenant_a_cannot_publish_tenant_b_document",
    ),
    MatrixRow(
        leg="knowledge",
        threat="IDOR",
        boundary="object storage",
        module="tests.security.test_tenant_isolation",
        test="test_object_key_of_a_is_rejected_under_tenant_b",
    ),
    MatrixRow(
        leg="config",
        threat="Spoofing de tenant",
        boundary="configuration store",
        module="tests.security.test_tenant_isolation",
        test="test_active_config_of_a_is_unreachable_from_tenant_b",
    ),
    MatrixRow(
        leg="secret",
        threat="Secret leakage",
        boundary="configuration/credentials reference",
        module="tests.security.test_tenant_isolation",
        test="test_credentials_reference_is_tenant_scoped_and_never_holds_values",
    ),
    MatrixRow(
        leg="job",
        threat="IDOR",
        boundary="job store",
        module="tests.security.test_tenant_isolation",
        test="test_reminder_job_of_a_is_invisible_and_immutable_from_b",
    ),
    MatrixRow(
        leg="audit",
        threat="Audit tampering",
        boundary="audit store",
        module="tests.security.test_tenant_isolation",
        test="test_audit_events_are_tenant_scoped_and_runtime_has_no_delete_api",
    ),
    MatrixRow(
        leg="tool",
        threat="Tool escalation",
        boundary="MCP capability",
        module="tests.security.test_tenant_isolation",
        test="test_tenant_a_cannot_cancel_tenant_b_appointment",
    ),
    MatrixRow(
        leg="tool",
        threat="Prompt injection",
        boundary="context compiler",
        module="tests.security.test_prompt_injection",
        test="test_pdf_injection_does_not_enable_tools_or_change_tenant",
    ),
    MatrixRow(
        leg="tool",
        threat="Tool escalation",
        boundary="tool executor",
        module="tests.security.test_prompt_injection",
        test="test_tool_outside_skill_allowlist_never_reaches_capability",
    ),
    MatrixRow(
        leg="tool",
        threat="Spoofing de tenant",
        boundary="tool arguments",
        module="tests.security.test_prompt_injection",
        test="test_injected_tenant_and_endpoint_arguments_are_rejected",
    ),
    MatrixRow(
        leg="tool",
        threat="SSRF",
        boundary="MCP resolver",
        module="tests.security.test_prompt_injection",
        test="test_endpoint_outside_host_allowlist_is_rejected_before_capability",
    ),
    MatrixRow(
        leg="tool",
        threat="Tool escalation",
        boundary="MCP resolver",
        module="tests.security.test_prompt_injection",
        test="test_resolver_allowlist_narrows_registry_decision",
    ),
    MatrixRow(
        leg="config",
        threat="Spoofing de tenant",
        boundary="channel gateway",
        module="tests.security.test_prompt_injection",
        test="test_signed_body_asking_for_another_tenant_stays_on_its_own_tenant",
    ),
    MatrixRow(
        leg="secret",
        threat="Secret leakage",
        boundary="central redactor",
        module="tests.security.test_redaction",
        test="test_redactor_removes_credentials_pii_and_connection_strings",
    ),
    MatrixRow(
        leg="secret",
        threat="Excessive data",
        boundary="handoff summary/outbox",
        module="tests.security.test_redaction",
        test="test_handoff_summary_and_outbox_redact_pii_and_secrets",
    ),
    MatrixRow(
        leg="secret",
        threat="Secret leakage",
        boundary="workflow store",
        module="tests.security.test_redaction",
        test="test_workflow_payload_and_presented_slots_drop_secret_material",
    ),
    MatrixRow(
        leg="audit",
        threat="Secret leakage",
        boundary="tool audit",
        module="tests.security.test_redaction",
        test="test_tool_audit_summary_omits_secret_values_and_endpoint",
    ),
)


def reset_schema() -> None:
    engine = create_engine(DATABASE_URL)
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))
    engine.dispose()
    alembic_cfg = Config(str(ROOT / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(ROOT / "alembic"))
    alembic_cfg.set_main_option("sqlalchemy.url", DATABASE_URL)
    command.upgrade(alembic_cfg, "head")


def seed_tenants_and_channels() -> None:
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


def config_draft(*, tone: str, credentials_reference: str) -> TenantConfigDraft:
    return TenantConfigDraft(
        agent=AgentConfig(tone=tone),
        enabled_skills=frozenset({"faq", "appointments"}),
        mcp=McpConfig(credentials_reference=credentials_reference),
    )


def appointment_config(tenant_id: UUID, *, version: int = 1) -> TenantConfig:
    return TenantConfig(
        tenant_id=tenant_id,
        version=version,
        agent=AgentConfig(tone="cordial"),
        enabled_skills=frozenset({"appointments"}),
        appointments=AppointmentPolicy(),
    )


def canary_slot(
    slot_id: str,
    *,
    practitioner: str,
    location: str,
    booking_token: str,
) -> AppointmentSlot:
    return AppointmentSlot(
        slot_id=slot_id,
        starts_at=SLOT_STARTS_AT,
        ends_at=SLOT_ENDS_AT,
        specialty="cardiologia",
        practitioner=practitioner,
        location=location,
        booking_token=SecretStr(booking_token),
    )


def two_tenant_capability(
    *, id_factory: str = "appt-b-1"
) -> FakeAppointmentCapability:
    return FakeAppointmentCapability(
        clock=lambda: CAPABILITY_CLOCK,
        id_factory=lambda: id_factory,
        initial_slots={
            TENANT_A: (
                canary_slot(
                    "slot-a-1",
                    practitioner="Dr. Ada",
                    location="sede-centro",
                    booking_token=CANARY_A_BOOKING_TOKEN,
                ),
            ),
            TENANT_B: (
                canary_slot(
                    "slot-b-1",
                    practitioner=CANARY_B_PRACTITIONER,
                    location=CANARY_B_LOCATION,
                    booking_token=CANARY_B_BOOKING_TOKEN,
                ),
            ),
        },
    )


def fresh_correlation_id() -> UUID:
    return uuid4()
