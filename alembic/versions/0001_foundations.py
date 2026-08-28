"""foundations tenant config schema

Revision ID: 0001_foundations
Revises:
"""

from collections.abc import Sequence

from alembic import op
from ia_mcp.configuration.adapters.sqlalchemy import metadata

revision: str = "0001_foundations"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    metadata.create_all(bind=bind)
    op.execute(
        """
        ALTER TABLE tenant
        ADD CONSTRAINT tenant_active_config_fk
        FOREIGN KEY (id, active_config_version)
        REFERENCES tenant_config (tenant_id, version)
        """
    )
    op.execute(
        """
        CREATE FUNCTION prevent_tenant_config_mutation()
        RETURNS trigger AS $$
        BEGIN
          RAISE EXCEPTION 'tenant_config is immutable';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER tenant_config_immutable
        BEFORE UPDATE ON tenant_config
        FOR EACH ROW EXECUTE FUNCTION prevent_tenant_config_mutation()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS tenant_config_immutable ON tenant_config")
    op.execute("DROP FUNCTION IF EXISTS prevent_tenant_config_mutation()")
    op.execute("ALTER TABLE tenant DROP CONSTRAINT IF EXISTS tenant_active_config_fk")
    bind = op.get_bind()
    metadata.drop_all(bind=bind)
