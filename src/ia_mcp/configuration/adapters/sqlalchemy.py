import json
import logging
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any
from uuid import UUID, uuid4

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
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from ia_mcp.configuration.models import (
    TenantAdminContext,
    TenantConfig,
    TenantConfigDraft,
)
from ia_mcp.configuration.ports import ConfigurationError
from ia_mcp.tenancy.models import TenantContext, TenantIdentity

logger = logging.getLogger("ia_mcp.configuration")

metadata = MetaData()

tenant_table = Table(
    "tenant",
    metadata,
    Column("id", PGUUID(as_uuid=True), primary_key=True),
    Column("slug", String(80), nullable=False, unique=True),
    Column("status", String(32), nullable=False),
    Column("active_config_version", Integer, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)

tenant_config_table = Table(
    "tenant_config",
    metadata,
    Column("tenant_id", PGUUID(as_uuid=True), nullable=False),
    Column("version", Integer, nullable=False),
    Column("schema_version", Integer, nullable=False),
    Column("status", String(32), nullable=False),
    Column("payload", JSONB, nullable=False),
    Column("content_hash", String(64), nullable=False),
    Column("created_by", PGUUID(as_uuid=True), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("published_at", DateTime(timezone=True), nullable=True),
    PrimaryKeyConstraint("tenant_id", "version"),
    ForeignKeyConstraint(["tenant_id"], ["tenant.id"]),
)

channel_integration_table = Table(
    "channel_integration",
    metadata,
    Column("id", PGUUID(as_uuid=True), nullable=False),
    Column("tenant_id", PGUUID(as_uuid=True), nullable=False),
    Column("channel", String(32), nullable=False),
    Column("external_account_id", String(255), nullable=False),
    Column("secret_reference", String(255), nullable=False),
    Column("status", String(32), nullable=False),
    PrimaryKeyConstraint("id"),
    UniqueConstraint("id", "tenant_id"),
    UniqueConstraint("channel", "external_account_id"),
    ForeignKeyConstraint(["tenant_id"], ["tenant.id"]),
)

audit_event_table = Table(
    "audit_event",
    metadata,
    Column("id", PGUUID(as_uuid=True), primary_key=True),
    Column("tenant_id", PGUUID(as_uuid=True), nullable=False),
    Column("actor_id", PGUUID(as_uuid=True), nullable=False),
    Column("action", String(64), nullable=False),
    Column("version", Integer, nullable=True),
    Column("payload", JSONB, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    ForeignKeyConstraint(["tenant_id"], ["tenant.id"]),
)


def payload_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return sha256(encoded.encode("utf-8")).hexdigest()


def _now() -> datetime:
    return datetime.now(UTC)


class SqlAlchemyConfigRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self._session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def publish(
        self, admin: TenantAdminContext, draft: TenantConfigDraft
    ) -> TenantConfig:
        payload = draft.model_dump(mode="json")
        digest = payload_hash(payload)
        async with self._session_factory() as session, session.begin():
            await self._ensure_tenant(session, admin)
            await session.execute(
                select(tenant_table.c.id)
                .where(tenant_table.c.id == admin.identity.tenant_id)
                .with_for_update()
            )
            current = await session.scalar(
                select(func.coalesce(func.max(tenant_config_table.c.version), 0)).where(
                    tenant_config_table.c.tenant_id == admin.identity.tenant_id
                )
            )
            version = int(current or 0) + 1
            published_at = _now()
            await session.execute(
                tenant_config_table.insert().values(
                    tenant_id=admin.identity.tenant_id,
                    version=version,
                    schema_version=draft.schema_version,
                    status="published",
                    payload=payload,
                    content_hash=digest,
                    created_by=admin.principal_id,
                    created_at=published_at,
                    published_at=published_at,
                )
            )
        return TenantConfig(tenant_id=admin.identity.tenant_id, version=version, **payload)

    async def activate(self, admin: TenantAdminContext, version: int) -> None:
        async with self._session_factory() as session, session.begin():
            row = await session.execute(
                select(tenant_config_table.c.version).where(
                    tenant_config_table.c.tenant_id == admin.identity.tenant_id,
                    tenant_config_table.c.version == version,
                )
            )
            if row.first() is None:
                raise ConfigurationError(
                    "not_found", "Configuration version is not available."
                )
            await session.execute(
                tenant_table.update()
                .where(tenant_table.c.id == admin.identity.tenant_id)
                .values(active_config_version=version, updated_at=_now())
            )

    async def get_active(self, identity: TenantIdentity) -> TenantConfig | None:
        async with self._session_factory() as session:
            tenant_row = (
                await session.execute(
                    select(tenant_table.c.active_config_version, tenant_table.c.slug).where(
                        tenant_table.c.id == identity.tenant_id
                    )
                )
            ).first()
            if tenant_row is None or tenant_row.active_config_version is None:
                return None
            if tenant_row.slug != identity.tenant_slug:
                return None
            return await self._load(
                session, identity.tenant_id, int(tenant_row.active_config_version)
            )

    async def get_version(self, identity: TenantIdentity, version: int) -> TenantConfig | None:
        async with self._session_factory() as session:
            return await self._load(session, identity.tenant_id, version)

    async def get_for_runtime(self, context: TenantContext) -> TenantConfig | None:
        async with self._session_factory() as session:
            tenant_row = (
                await session.execute(
                    select(tenant_table.c.slug).where(tenant_table.c.id == context.tenant_id)
                )
            ).first()
            if tenant_row is None:
                return None
            if tenant_row.slug != context.tenant_slug:
                logger.warning("tenant_isolation_violation")
                raise ConfigurationError(
                    "tenant_isolation_violation",
                    "Configuration does not belong to this tenant.",
                )
            config = await self._load(session, context.tenant_id, context.config_version)
            if config is None:
                return None
            if config.tenant_id != context.tenant_id:
                logger.warning("tenant_isolation_violation")
                raise ConfigurationError(
                    "tenant_isolation_violation",
                    "Configuration does not belong to this tenant.",
                )
            return config

    async def record_audit(
        self, admin: TenantAdminContext, action: str, version: int
    ) -> None:
        async with self._session_factory() as session, session.begin():
            await session.execute(
                audit_event_table.insert().values(
                    id=uuid4(),
                    tenant_id=admin.identity.tenant_id,
                    actor_id=admin.principal_id,
                    action=action,
                    version=version,
                    created_at=_now(),
                )
            )

    async def _ensure_tenant(
        self, session: AsyncSession, admin: TenantAdminContext
    ) -> None:
        now = _now()
        await session.execute(
            pg_insert(tenant_table)
            .values(
                id=admin.identity.tenant_id,
                slug=admin.identity.tenant_slug,
                status="active",
                active_config_version=None,
                created_at=now,
                updated_at=now,
            )
            .on_conflict_do_nothing(index_elements=["id"])
        )

    async def _load(
        self, session: AsyncSession, tenant_id: UUID, version: int
    ) -> TenantConfig | None:
        row = (
            await session.execute(
                select(tenant_config_table).where(
                    tenant_config_table.c.tenant_id == tenant_id,
                    tenant_config_table.c.version == version,
                )
            )
        ).mappings().first()
        if row is None:
            return None
        payload = dict(row["payload"])
        return TenantConfig(tenant_id=row["tenant_id"], version=row["version"], **payload)
