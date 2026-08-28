"""onboarding integration references

Revision ID: 0007_onboarding
Revises: 0006_scheduling
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0007_onboarding"
down_revision: str | Sequence[str] | None = "0006_scheduling"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "integration",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("server_id", sa.String(length=255), nullable=True),
        sa.Column("credentials_reference", sa.String(length=255), nullable=False),
        sa.Column("capabilities", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "tenant_id"),
        sa.UniqueConstraint("tenant_id", "kind", "credentials_reference"),
    )


def downgrade() -> None:
    op.drop_table("integration")
