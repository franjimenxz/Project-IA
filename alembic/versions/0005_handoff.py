"""handoff cases

Revision ID: 0005_handoff
Revises: 0004_workflows
"""

from collections.abc import Sequence

from alembic import op
from ia_mcp.handoff.service import metadata

revision: str = "0005_handoff"
down_revision: str | Sequence[str] | None = "0004_workflows"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    metadata.create_all(bind=bind)
    op.create_foreign_key(
        "fk_handoff_tenant",
        "handoff",
        "tenant",
        ["tenant_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_handoff_conversation",
        "handoff",
        "conversation",
        ["tenant_id", "conversation_id"],
        ["tenant_id", "id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_handoff_conversation", "handoff", type_="foreignkey")
    op.drop_constraint("fk_handoff_tenant", "handoff", type_="foreignkey")
    bind = op.get_bind()
    metadata.drop_all(bind=bind)
