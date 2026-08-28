"""scheduled jobs and scheduling outbox

Revision ID: 0006_scheduling
Revises: 0005_handoff
"""

from collections.abc import Sequence

from alembic import op
from ia_mcp.scheduling.service import metadata

revision: str = "0006_scheduling"
down_revision: str | Sequence[str] | None = "0005_handoff"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    metadata.create_all(bind=bind)
    op.create_foreign_key(
        "fk_scheduled_job_tenant",
        "scheduled_job",
        "tenant",
        ["tenant_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_scheduled_job_tenant", "scheduled_job", type_="foreignkey")
    bind = op.get_bind()
    metadata.drop_all(bind=bind)
