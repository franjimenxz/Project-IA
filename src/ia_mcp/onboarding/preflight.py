from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Literal, Protocol
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
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
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from ia_mcp.configuration.adapters.sqlalchemy import (
    channel_integration_table,
    tenant_config_table,
    tenant_table,
)
from ia_mcp.configuration.models import TenantConfigDraft
from ia_mcp.knowledge.adapters.sqlalchemy import SqlAlchemyKnowledgeRepository
from ia_mcp.observability.redaction import redact
from ia_mcp.observability.run_query import RunInvestigationQuery, RunNotFound
from ia_mcp.shared.errors import TenantIsolationViolation
from ia_mcp.tenancy.models import TenantContext

type CheckSeverity = Literal["critical", "warning"]

PREFLIGHT_CHECK_NAMES: tuple[str, ...] = (
    "schema_policy",
    "secrets_resolvable",
    "unique_channel",
    "retrieval_canary",
    "mcp_health",
    "eval_smoke",
    "observability",
    "rollback_inputs",
)

metadata = MetaData()

preflight_report_table = Table(
    "preflight_report",
    metadata,
    Column("id", PGUUID(as_uuid=True), nullable=False),
    Column("tenant_id", PGUUID(as_uuid=True), nullable=False),
    Column("report_hash", String(64), nullable=False),
    Column("content_hash", String(64), nullable=False),
    Column("config_hash", String(64), nullable=False),
    Column("passed", Boolean, nullable=False),
    Column("checks", JSONB, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    PrimaryKeyConstraint("id"),
    UniqueConstraint("report_hash"),
    UniqueConstraint("tenant_id", "report_hash"),
)

tenant_onboarding_state_table = Table(
    "tenant_onboarding_state",
    metadata,
    Column("tenant_id", PGUUID(as_uuid=True), nullable=False),
    Column("package_content_hash", String(64), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    PrimaryKeyConstraint("tenant_id"),
)


class CheckOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    passed: bool
    severity: CheckSeverity
    code: str
    message: str


class PreflightReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    report_hash: str
    tenant_id: UUID
    content_hash: str
    config_hash: str
    passed: bool
    checks: tuple[CheckOutcome, ...]
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class RetrievalCanaryObservation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    published: bool
    own_hit: bool
    foreign_hit: bool


class PreflightCheckPort(Protocol):
    name: str

    async def run(self, tenant: TenantContext) -> CheckOutcome: ...


class SecretReferencePort(Protocol):
    async def resolvable(self, tenant: TenantContext, reference: str) -> bool: ...


class RetrievalCanaryPort(Protocol):
    async def observe(self, tenant: TenantContext) -> RetrievalCanaryObservation: ...


class McpHealthPort(Protocol):
    async def healthy(self, tenant: TenantContext) -> bool: ...


class EvalSmokePort(Protocol):
    async def passed(self, tenant: TenantContext) -> bool: ...


def compute_report_hash(
    *,
    tenant_id: UUID,
    content_hash: str,
    config_hash: str,
    checks: Sequence[CheckOutcome],
) -> str:
    payload = {
        "tenant_id": str(tenant_id),
        "content_hash": content_hash,
        "config_hash": config_hash,
        "checks": [
            {
                "name": item.name,
                "passed": item.passed,
                "severity": item.severity,
                "code": item.code,
            }
            for item in checks
        ],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


async def collect_check_outcomes(
    tenant: TenantContext,
    checks: Sequence[PreflightCheckPort],
) -> tuple[CheckOutcome, ...]:
    by_name = {check.name: check for check in checks}
    outcomes: list[CheckOutcome] = []
    for name in PREFLIGHT_CHECK_NAMES:
        port = by_name.get(name)
        if port is None:
            outcomes.append(
                CheckOutcome(
                    name=name,
                    passed=False,
                    severity="critical",
                    code="missing_check",
                    message="Required preflight check is missing.",
                )
            )
            continue
        result = await port.run(tenant)
        outcomes.append(
            CheckOutcome(
                name=name,
                passed=result.passed,
                severity=result.severity,
                code=result.code,
                message=redact(result.message),
            )
        )
    return tuple(outcomes)


def report_from_outcomes(
    *,
    tenant_id: UUID,
    content_hash: str,
    config_hash: str,
    checks: tuple[CheckOutcome, ...],
    created_at: datetime | None = None,
) -> PreflightReport:
    passed = all(item.passed for item in checks)
    return PreflightReport(
        report_hash=compute_report_hash(
            tenant_id=tenant_id,
            content_hash=content_hash,
            config_hash=config_hash,
            checks=checks,
        ),
        tenant_id=tenant_id,
        content_hash=content_hash,
        config_hash=config_hash,
        passed=passed,
        checks=checks,
        created_at=created_at or datetime.now(UTC),
    )


def default_preflight_checks(
    engine: AsyncEngine,
    *,
    investigation_query: RunInvestigationQuery | None = None,
    secrets: SecretReferencePort | None = None,
    retrieval: RetrievalCanaryPort | None = None,
    mcp_health: McpHealthPort | None = None,
    eval_smoke: EvalSmokePort | None = None,
) -> tuple[PreflightCheckPort, ...]:
    return (
        SchemaPolicyCheck(engine),
        SecretResolvabilityCheck(engine, secrets or _FailClosedSecrets()),
        UniqueChannelCheck(engine),
        RetrievalCanaryCheck(retrieval or KnowledgeStoreRetrieval(engine)),
        McpHealthCheck(mcp_health or _FailClosedMcp()),
        EvalSmokeCheck(eval_smoke or _FailClosedEval()),
        ObservabilityQueryCheck(investigation_query),
        RollbackInputsCheck(engine),
    )


class SchemaPolicyCheck:
    name = "schema_policy"

    def __init__(self, engine: AsyncEngine) -> None:
        self._sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def run(self, tenant: TenantContext) -> CheckOutcome:
        async with self._sessions() as session:
            row = (
                await session.execute(
                    select(tenant_config_table.c.payload).where(
                        tenant_config_table.c.tenant_id == tenant.tenant_id
                    )
                )
            ).first()
        if row is None:
            return _failed(self.name, "config_missing", "Tenant configuration is missing.")
        try:
            TenantConfigDraft.model_validate(row[0])
        except ValueError:
            return _failed(self.name, "config_invalid", "Tenant configuration is invalid.")
        return _passed(self.name)


class SecretResolvabilityCheck:
    name = "secrets_resolvable"

    def __init__(self, engine: AsyncEngine, secrets: SecretReferencePort) -> None:
        self._sessions = async_sessionmaker(engine, expire_on_commit=False)
        self._secrets = secrets

    async def run(self, tenant: TenantContext) -> CheckOutcome:
        references = await _secret_references(self._sessions, tenant)
        if not references:
            return _failed(self.name, "secrets_missing", "Secret references are missing.")
        for reference in references:
            if not reference.startswith("sm://"):
                return _failed(
                    self.name, "secret_literal", "Secret values are forbidden."
                )
            if not await self._secrets.resolvable(tenant, reference):
                return _failed(
                    self.name,
                    "secret_unresolved",
                    "Secret references are not resolvable.",
                )
        return _passed(self.name)


class UniqueChannelCheck:
    name = "unique_channel"

    def __init__(self, engine: AsyncEngine) -> None:
        self._sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def run(self, tenant: TenantContext) -> CheckOutcome:
        async with self._sessions() as session:
            rows = (
                await session.execute(
                    select(
                        channel_integration_table.c.channel,
                        channel_integration_table.c.external_account_id,
                    ).where(channel_integration_table.c.tenant_id == tenant.tenant_id)
                )
            ).all()
        if not rows:
            return _failed(self.name, "channel_missing", "Channel mapping is missing.")
        keys = [(row[0], row[1]) for row in rows]
        if len(keys) != len(set(keys)):
            return _failed(self.name, "duplicate_channel", "Channel mapping must be unique.")
        return _passed(self.name)


_CANARY_RE = re.compile(r"canary-([a-z0-9]+(?:-[a-z0-9]+)*)")


class KnowledgeStoreRetrieval:
    def __init__(self, engine: AsyncEngine) -> None:
        self._repository = SqlAlchemyKnowledgeRepository(engine)

    async def observe(self, tenant: TenantContext) -> RetrievalCanaryObservation:
        chunks = await self._repository.search_published(tenant, 50)
        if not chunks:
            return RetrievalCanaryObservation(
                published=False, own_hit=False, foreign_hit=False
            )
        own_hit = False
        foreign_hit = False
        for chunk in chunks:
            if chunk.tenant_id != tenant.tenant_id:
                foreign_hit = True
                continue
            for marker in _CANARY_RE.findall(chunk.text):
                if marker == tenant.tenant_slug:
                    own_hit = True
                else:
                    foreign_hit = True
        return RetrievalCanaryObservation(
            published=True, own_hit=own_hit, foreign_hit=foreign_hit
        )


class RetrievalCanaryCheck:
    name = "retrieval_canary"

    def __init__(self, retrieval: RetrievalCanaryPort) -> None:
        self._retrieval = retrieval

    async def run(self, tenant: TenantContext) -> CheckOutcome:
        observed = await self._retrieval.observe(tenant)
        if not observed.published:
            return _failed(
                self.name,
                "knowledge_unpublished",
                "Knowledge is not published.",
            )
        if observed.foreign_hit:
            return _failed(
                self.name,
                "foreign_canary",
                "Retrieval returned a foreign canary.",
            )
        if not observed.own_hit:
            return _failed(
                self.name,
                "own_canary_missing",
                "Retrieval did not return the tenant canary.",
            )
        return _passed(self.name)


class McpHealthCheck:
    name = "mcp_health"

    def __init__(self, mcp_health: McpHealthPort) -> None:
        self._mcp_health = mcp_health

    async def run(self, tenant: TenantContext) -> CheckOutcome:
        if not await self._mcp_health.healthy(tenant):
            return _failed(self.name, "mcp_unhealthy", "MCP health check failed.")
        return _passed(self.name)


class EvalSmokeCheck:
    name = "eval_smoke"

    def __init__(self, eval_smoke: EvalSmokePort) -> None:
        self._eval_smoke = eval_smoke

    async def run(self, tenant: TenantContext) -> CheckOutcome:
        if not await self._eval_smoke.passed(tenant):
            return _failed(self.name, "eval_smoke_failed", "Eval smoke did not pass.")
        return _passed(self.name)


class ObservabilityQueryCheck:
    name = "observability"

    def __init__(self, query: RunInvestigationQuery | None) -> None:
        self._query = query

    async def run(self, tenant: TenantContext) -> CheckOutcome:
        if self._query is None:
            return _failed(
                self.name,
                "observability_unavailable",
                "Observability query is not available.",
            )
        try:
            await self._query.get(tenant, uuid4())
        except RunNotFound:
            return _passed(self.name, code="observability_ready")
        except TenantIsolationViolation:
            return _failed(
                self.name,
                "observability_isolation",
                "Observability query violated tenant isolation.",
            )
        return _passed(self.name, code="observability_ready")


class RollbackInputsCheck:
    name = "rollback_inputs"

    def __init__(self, engine: AsyncEngine) -> None:
        self._sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def run(self, tenant: TenantContext) -> CheckOutcome:
        async with self._sessions() as session:
            tenant_row = (
                await session.execute(
                    select(tenant_table.c.id, tenant_table.c.slug).where(
                        tenant_table.c.id == tenant.tenant_id
                    )
                )
            ).first()
            config_row = (
                await session.execute(
                    select(tenant_config_table.c.version).where(
                        tenant_config_table.c.tenant_id == tenant.tenant_id
                    )
                )
            ).first()
            mapping = (
                await session.execute(
                    select(channel_integration_table.c.id).where(
                        channel_integration_table.c.tenant_id == tenant.tenant_id
                    )
                )
            ).first()
        if tenant_row is None or tenant_row.slug != tenant.tenant_slug:
            return _failed(self.name, "tenant_missing", "Tenant is not available.")
        if config_row is None or mapping is None:
            return _failed(
                self.name, "rollback_inputs_missing", "Rollback inputs are missing."
            )
        return _passed(self.name)


class _FailClosedSecrets:
    async def resolvable(self, tenant: TenantContext, reference: str) -> bool:
        return False


class _FailClosedMcp:
    async def healthy(self, tenant: TenantContext) -> bool:
        return False


class _FailClosedEval:
    async def passed(self, tenant: TenantContext) -> bool:
        return False


def _passed(name: str, *, code: str = "ok") -> CheckOutcome:
    return CheckOutcome(
        name=name,
        passed=True,
        severity="critical",
        code=code,
        message="ok",
    )


def _failed(name: str, code: str, message: str) -> CheckOutcome:
    return CheckOutcome(
        name=name,
        passed=False,
        severity="critical",
        code=code,
        message=message,
    )


async def _secret_references(
    sessions: async_sessionmaker[AsyncSession], tenant: TenantContext
) -> tuple[str, ...]:
    async with sessions() as session:
        channels = (
            await session.execute(
                select(channel_integration_table.c.secret_reference).where(
                    channel_integration_table.c.tenant_id == tenant.tenant_id
                )
            )
        ).scalars().all()
        integrations = (
            (
                await session.execute(
                    text(
                        "SELECT credentials_reference FROM integration "
                        "WHERE tenant_id = :tenant_id"
                    ),
                    {"tenant_id": tenant.tenant_id},
                )
            )
            .scalars()
            .all()
        )
        payload = (
            await session.execute(
                select(tenant_config_table.c.payload).where(
                    tenant_config_table.c.tenant_id == tenant.tenant_id
                )
            )
        ).scalar_one_or_none()
    refs = [str(item) for item in channels] + [str(item) for item in integrations]
    if isinstance(payload, dict):
        for section in ("appointments", "knowledge", "mcp", "handoff"):
            value = payload.get(section)
            if isinstance(value, dict):
                reference = value.get("credentials_reference")
                if isinstance(reference, str) and reference:
                    refs.append(reference)
    return tuple(refs)
