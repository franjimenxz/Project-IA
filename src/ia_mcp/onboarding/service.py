from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

from sqlalchemy import (
    Column,
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
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from ia_mcp.configuration.adapters.sqlalchemy import (
    audit_event_table,
    channel_integration_table,
    payload_hash,
    tenant_config_table,
    tenant_table,
)
from ia_mcp.configuration.models import (
    AppointmentPolicy,
    HandoffPolicy,
    KnowledgeConfig,
    McpConfig,
    TenantAdminContext,
    TenantConfigDraft,
)
from ia_mcp.observability.redaction import redact
from ia_mcp.onboarding.commands import (
    ConfigLifecycleStatus,
    OnboardingError,
    Principal,
    ProvisionedTenant,
    TenantLifecycleStatus,
)
from ia_mcp.onboarding.models import TenantPackage
from ia_mcp.scheduling.service import scheduled_job_table
from ia_mcp.shared.errors import TenantIsolationViolation
from ia_mcp.tenancy.models import ChannelIntegration, TenantIdentity

PLATFORM_ADMIN = "platform_admin"
TENANT_ADMIN = "tenant_admin"
type ProvisionIntegrity = Literal["slug_race", "channel_conflict"]

metadata = MetaData()

integration_table = Table(
    "integration",
    metadata,
    Column("id", PGUUID(as_uuid=True), nullable=False),
    Column("tenant_id", PGUUID(as_uuid=True), nullable=False),
    Column("kind", String(32), nullable=False),
    Column("server_id", String(255), nullable=True),
    Column("credentials_reference", String(255), nullable=False),
    Column("capabilities", JSONB, nullable=False),
    Column("status", String(32), nullable=False),
    PrimaryKeyConstraint("id"),
    UniqueConstraint("id", "tenant_id"),
    UniqueConstraint("tenant_id", "kind", "credentials_reference"),
)


def classify_provision_integrity(exc: IntegrityError) -> ProvisionIntegrity:
    orig = exc.orig
    name = ""
    diag = getattr(orig, "diag", None)
    if diag is not None:
        name = str(getattr(diag, "constraint_name", "") or "")
    message = str(orig) if orig is not None else str(exc)
    blob = f"{name} {message}".lower()
    if "tenant_slug" in blob or "key (slug)" in blob:
        return "slug_race"
    return "channel_conflict"


class _SlugRace(Exception):
    pass


def _now() -> datetime:
    return datetime.now(UTC)


def _draft_from_package(package: TenantPackage) -> TenantConfigDraft:
    return TenantConfigDraft(
        schema_version=1,
        agent=package.config.agent,
        enabled_skills=frozenset(package.config.enabled_skills),
        appointments=AppointmentPolicy(
            required_fields=package.config.appointments.required_fields,
            credentials_reference=package.config.appointments.credentials_reference,
        ),
        knowledge=KnowledgeConfig(
            credentials_reference=package.config.knowledge.credentials_reference,
        ),
        mcp=McpConfig(
            credentials_reference=package.config.mcp.credentials_reference,
        ),
        handoff=HandoffPolicy(
            credentials_reference=package.config.handoff.credentials_reference,
        ),
        feature_flags=dict(package.config.feature_flags),
    )


def _tenant_status(value: str) -> TenantLifecycleStatus:
    if value == "provisioning":
        return "provisioning"
    if value == "active":
        return "active"
    if value == "suspended":
        return "suspended"
    return "disabled"


def _config_status(value: str) -> ConfigLifecycleStatus:
    if value == "validated":
        return "validated"
    if value == "published":
        return "published"
    if value == "retired":
        return "retired"
    return "draft"


def _provisioned(
    row: Any, config_version: int, config_status: str
) -> ProvisionedTenant:
    return ProvisionedTenant(
        identity=TenantIdentity(tenant_id=row["id"], tenant_slug=row["slug"]),
        status=_tenant_status(str(row["status"])),
        config_version=config_version,
        config_status=_config_status(config_status),
    )


class SqlAlchemyOnboardingStore:
    def __init__(self, engine: AsyncEngine) -> None:
        self._sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def get_by_slug(self, slug: str) -> ProvisionedTenant | None:
        async with self._sessions() as session:
            return await self._load_by_slug(session, slug)

    async def provision(
        self, package: TenantPackage, actor: Principal
    ) -> ProvisionedTenant:
        slug = package.tenant.slug
        try:
            async with self._sessions() as session, session.begin():
                # hashtext is int4; collisions are possible. Unique slug + replay is authoritative.
                await session.execute(
                    text("SELECT pg_advisory_xact_lock(hashtext(:slug))"),
                    {"slug": slug},
                )
                existing = await self._load_by_slug(session, slug)
                if existing is not None:
                    return existing
                tenant_id = uuid4()
                now = _now()
                draft = _draft_from_package(package)
                payload = draft.model_dump(mode="json")
                try:
                    await session.execute(
                        tenant_table.insert().values(
                            id=tenant_id,
                            slug=slug,
                            status="disabled",
                            active_config_version=None,
                            created_at=now,
                            updated_at=now,
                        )
                    )
                    await session.execute(
                        tenant_config_table.insert().values(
                            tenant_id=tenant_id,
                            version=int(package.config.version),
                            schema_version=draft.schema_version,
                            status="draft",
                            payload=payload,
                            content_hash=payload_hash(payload),
                            created_by=actor.principal_id,
                            created_at=now,
                            published_at=None,
                        )
                    )
                    for channel in package.integrations.channels:
                        await session.execute(
                            channel_integration_table.insert().values(
                                id=uuid4(),
                                tenant_id=tenant_id,
                                channel=channel.channel,
                                external_account_id=channel.external_account_id,
                                secret_reference=channel.secret_reference,
                                status="disabled",
                            )
                        )
                    for binding in package.integrations.integrations:
                        await session.execute(
                            integration_table.insert().values(
                                id=uuid4(),
                                tenant_id=tenant_id,
                                kind=binding.kind,
                                server_id=binding.server_id,
                                credentials_reference=binding.credentials_reference,
                                capabilities=list(binding.capabilities),
                                status="disabled",
                            )
                        )
                    await session.execute(
                        audit_event_table.insert().values(
                            id=uuid4(),
                            tenant_id=tenant_id,
                            actor_id=actor.principal_id,
                            action="provision",
                            version=int(package.config.version),
                            created_at=now,
                        )
                    )
                except IntegrityError as exc:
                    if classify_provision_integrity(exc) == "slug_race":
                        raise _SlugRace from exc
                    raise OnboardingError(
                        "channel_conflict",
                        "Channel mapping is not available.",
                        retryable=False,
                    ) from exc
                return ProvisionedTenant(
                    identity=TenantIdentity(tenant_id=tenant_id, tenant_slug=slug),
                    status="disabled",
                    config_version=int(package.config.version),
                    config_status="draft",
                )
        except _SlugRace:
            replayed = await self.get_by_slug(slug)
            if replayed is None:
                raise OnboardingError(
                    "channel_conflict",
                    "Channel mapping is not available.",
                    retryable=False,
                )
            return replayed

    async def disable(self, admin: TenantAdminContext, reason: str) -> None:
        sanitized_reason = redact(reason.strip())
        async with self._sessions() as session, session.begin():
            row = (
                (
                    await session.execute(
                        select(tenant_table)
                        .where(tenant_table.c.id == admin.identity.tenant_id)
                        .with_for_update()
                    )
                )
                .mappings()
                .first()
            )
            if row is None or row["slug"] != admin.identity.tenant_slug:
                raise TenantIsolationViolation()
            now = _now()
            await session.execute(
                tenant_table.update()
                .where(tenant_table.c.id == admin.identity.tenant_id)
                .values(status="disabled", updated_at=now)
            )
            await session.execute(
                channel_integration_table.update()
                .where(
                    channel_integration_table.c.tenant_id == admin.identity.tenant_id
                )
                .values(status="disabled")
            )
            await session.execute(
                integration_table.update()
                .where(integration_table.c.tenant_id == admin.identity.tenant_id)
                .values(status="disabled")
            )
            await session.execute(
                scheduled_job_table.update()
                .where(
                    scheduled_job_table.c.tenant_id == admin.identity.tenant_id,
                    scheduled_job_table.c.status.in_(("pending", "claimed")),
                )
                .values(
                    status="cancelled",
                    lock_owner=None,
                    lock_expires_at=None,
                    updated_at=now,
                )
            )
            await session.execute(
                audit_event_table.insert().values(
                    id=uuid4(),
                    tenant_id=admin.identity.tenant_id,
                    actor_id=admin.principal_id,
                    action="disable",
                    version=None,
                    payload={"reason": sanitized_reason},
                    created_at=now,
                )
            )

    async def require_active(self, identity: TenantIdentity) -> None:
        async with self._sessions() as session:
            row = (
                await session.execute(
                    select(tenant_table.c.slug, tenant_table.c.status).where(
                        tenant_table.c.id == identity.tenant_id
                    )
                )
            ).first()
            if row is None or row.slug != identity.tenant_slug:
                raise TenantIsolationViolation()
            if row.status != "active":
                raise OnboardingError(
                    "tenant_disabled",
                    "Tenant is not available.",
                )

    async def get(self, channel: str, account_id: str) -> ChannelIntegration | None:
        async with self._sessions() as session:
            row = (
                await session.execute(
                    select(
                        channel_integration_table.c.tenant_id,
                        channel_integration_table.c.status,
                        tenant_table.c.slug,
                    )
                    .select_from(
                        channel_integration_table.join(
                            tenant_table,
                            tenant_table.c.id == channel_integration_table.c.tenant_id,
                        )
                    )
                    .where(
                        channel_integration_table.c.channel == channel,
                        channel_integration_table.c.external_account_id == account_id,
                    )
                )
            ).first()
            if row is None:
                return None
            return ChannelIntegration(
                tenant_id=row.tenant_id,
                tenant_slug=row.slug,
                enabled=row.status == "active",
            )

    async def _load_by_slug(
        self, session: AsyncSession, slug: str
    ) -> ProvisionedTenant | None:
        tenant = (
            (
                await session.execute(
                    select(tenant_table).where(tenant_table.c.slug == slug)
                )
            )
            .mappings()
            .first()
        )
        if tenant is None:
            return None
        version_row = (
            await session.execute(
                select(tenant_config_table.c.version, tenant_config_table.c.status)
                .where(tenant_config_table.c.tenant_id == tenant["id"])
                .order_by(tenant_config_table.c.version.desc())
                .limit(1)
            )
        ).first()
        if version_row is None:
            return _provisioned(tenant, 0, "draft")
        return _provisioned(tenant, int(version_row.version), str(version_row.status))


class TenantOnboardingService:
    def __init__(self, engine: AsyncEngine) -> None:
        self._store = SqlAlchemyOnboardingStore(engine)

    async def get_by_slug(self, slug: str) -> ProvisionedTenant | None:
        return await self._store.get_by_slug(slug)

    async def provision(
        self, package: TenantPackage, actor: Principal
    ) -> ProvisionedTenant:
        _require_platform_admin(actor.roles)
        return await self._store.provision(package, actor)

    async def disable(self, admin: TenantAdminContext, reason: str) -> None:
        if not reason.strip():
            raise OnboardingError("invalid_reason", "A disable reason is required.")
        _require_disable_role(admin)
        await self._store.disable(admin, reason)

    async def require_active(self, identity: TenantIdentity) -> None:
        await self._store.require_active(identity)

    async def get(self, channel: str, account_id: str) -> ChannelIntegration | None:
        return await self._store.get(channel, account_id)


def admin_context_for(
    principal: Principal, tenant: ProvisionedTenant
) -> TenantAdminContext:
    if PLATFORM_ADMIN in principal.roles:
        return TenantAdminContext(
            identity=tenant.identity,
            principal_id=principal.principal_id,
            roles=principal.roles,
            correlation_id=uuid4(),
        )
    if TENANT_ADMIN in principal.roles:
        if (
            principal.tenant_id != tenant.identity.tenant_id
            or principal.tenant_slug != tenant.identity.tenant_slug
        ):
            raise TenantIsolationViolation()
        return TenantAdminContext(
            identity=tenant.identity,
            principal_id=principal.principal_id,
            roles=principal.roles,
            correlation_id=uuid4(),
        )
    raise OnboardingError(
        "forbidden",
        "Administrator is not allowed to perform this action.",
    )


def _require_platform_admin(roles: frozenset[str]) -> None:
    if PLATFORM_ADMIN not in roles:
        raise OnboardingError(
            "forbidden",
            "Administrator is not allowed to perform this action.",
        )


def _require_disable_role(admin: TenantAdminContext) -> None:
    if PLATFORM_ADMIN in admin.roles:
        return
    if TENANT_ADMIN in admin.roles:
        return
    raise OnboardingError(
        "forbidden",
        "Administrator is not allowed to perform this action.",
    )
