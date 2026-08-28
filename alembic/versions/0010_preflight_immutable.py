"""forbid update and delete on preflight_report

Revision ID: 0010_preflight_immutable
Revises: 0009_preflight
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0010_preflight_immutable"
down_revision: str | Sequence[str] | None = "0009_preflight"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE FUNCTION prevent_preflight_report_mutation()
        RETURNS trigger AS $$
        BEGIN
          RAISE EXCEPTION 'preflight_report is immutable';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER preflight_report_immutable
        BEFORE UPDATE OR DELETE ON preflight_report
        FOR EACH ROW EXECUTE FUNCTION prevent_preflight_report_mutation()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS preflight_report_immutable ON preflight_report")
    op.execute("DROP FUNCTION IF EXISTS prevent_preflight_report_mutation()")
