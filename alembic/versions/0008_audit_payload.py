"""audit event payload for sanitized disable reasons

Revision ID: 0008_audit_payload
Revises: 0007_onboarding
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0008_audit_payload"
down_revision: str | Sequence[str] | None = "0007_onboarding"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE audit_event ADD COLUMN IF NOT EXISTS payload JSONB")


def downgrade() -> None:
    op.execute("ALTER TABLE audit_event DROP COLUMN IF EXISTS payload")
