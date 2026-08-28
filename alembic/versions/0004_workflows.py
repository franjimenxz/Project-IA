"""workflow executions transitions and outbox

Revision ID: 0004_workflows
Revises: 0003_knowledge
"""

from collections.abc import Sequence

from alembic import op
from ia_mcp.workflows.adapters.sqlalchemy import metadata

revision: str = "0004_workflows"
down_revision: str | Sequence[str] | None = "0003_knowledge"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    metadata.create_all(bind=bind)
    op.create_foreign_key(
        "fk_workflow_execution_tenant",
        "workflow_execution",
        "tenant",
        ["tenant_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_outbox_event_tenant",
        "outbox_event",
        "tenant",
        ["tenant_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_outbox_event_tenant", "outbox_event", type_="foreignkey")
    op.drop_constraint(
        "fk_workflow_execution_tenant", "workflow_execution", type_="foreignkey"
    )
    bind = op.get_bind()
    metadata.drop_all(bind=bind)
