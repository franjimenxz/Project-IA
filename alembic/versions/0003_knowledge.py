"""knowledge documents versions and chunks

Revision ID: 0003_knowledge
Revises: 0002_conversations
"""

from collections.abc import Sequence

from alembic import op
from ia_mcp.knowledge.adapters.sqlalchemy import metadata

revision: str = "0003_knowledge"
down_revision: str | Sequence[str] | None = "0002_conversations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    metadata.create_all(bind=bind)
    op.create_foreign_key(
        "fk_knowledge_document_tenant",
        "knowledge_document",
        "tenant",
        ["tenant_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_knowledge_document_tenant", "knowledge_document", type_="foreignkey"
    )
    bind = op.get_bind()
    metadata.drop_all(bind=bind)
