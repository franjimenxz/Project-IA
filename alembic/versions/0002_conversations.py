"""conversations messages session state and agent runs

Revision ID: 0002_conversations
Revises: 0001_foundations
"""

from collections.abc import Sequence

from alembic import op
from ia_mcp.agent_runtime.run_repository import metadata as run_metadata
from ia_mcp.conversation.adapters.sqlalchemy import metadata as conversation_metadata

revision: str = "0002_conversations"
down_revision: str | Sequence[str] | None = "0001_foundations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    conversation_metadata.create_all(bind=bind)
    run_metadata.create_all(bind=bind)
    op.create_foreign_key(
        "fk_conversation_tenant",
        "conversation",
        "tenant",
        ["tenant_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_conversation_channel_integration",
        "conversation",
        "channel_integration",
        ["channel_integration_id", "tenant_id"],
        ["id", "tenant_id"],
    )
    op.create_foreign_key(
        "fk_message_channel_integration",
        "message",
        "channel_integration",
        ["channel_integration_id", "tenant_id"],
        ["id", "tenant_id"],
    )
    op.create_foreign_key(
        "fk_agent_run_tenant",
        "agent_run",
        "tenant",
        ["tenant_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_agent_run_conversation",
        "agent_run",
        "conversation",
        ["tenant_id", "conversation_id"],
        ["tenant_id", "id"],
    )
    op.create_foreign_key(
        "fk_agent_run_input_message",
        "agent_run",
        "message",
        ["tenant_id", "input_message_id"],
        ["tenant_id", "id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_agent_run_input_message", "agent_run", type_="foreignkey")
    op.drop_constraint("fk_agent_run_conversation", "agent_run", type_="foreignkey")
    op.drop_constraint("fk_agent_run_tenant", "agent_run", type_="foreignkey")
    op.drop_constraint("fk_message_channel_integration", "message", type_="foreignkey")
    op.drop_constraint(
        "fk_conversation_channel_integration", "conversation", type_="foreignkey"
    )
    op.drop_constraint("fk_conversation_tenant", "conversation", type_="foreignkey")
    bind = op.get_bind()
    run_metadata.drop_all(bind=bind)
    conversation_metadata.drop_all(bind=bind)
