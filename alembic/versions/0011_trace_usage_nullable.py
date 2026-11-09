"""Store unknown model usage and cost as null, with decimal cost precision."""

from alembic import op

revision = "0011_trace_usage_nullable"
down_revision = "0010_run_ticket_draft"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE traces ALTER COLUMN tokens DROP DEFAULT")
    op.execute("ALTER TABLE traces ALTER COLUMN cost DROP DEFAULT")
    op.execute("ALTER TABLE traces ALTER COLUMN tokens DROP NOT NULL")
    op.execute("ALTER TABLE traces ALTER COLUMN cost TYPE NUMERIC(12, 8) USING cost::numeric")
    op.execute("ALTER TABLE traces ALTER COLUMN cost DROP NOT NULL")


def downgrade() -> None:
    op.execute("UPDATE traces SET tokens = 0 WHERE tokens IS NULL")
    op.execute("UPDATE traces SET cost = 0 WHERE cost IS NULL")
    op.execute("ALTER TABLE traces ALTER COLUMN cost TYPE INTEGER USING round(cost)::integer")
    op.execute("ALTER TABLE traces ALTER COLUMN tokens SET NOT NULL")
    op.execute("ALTER TABLE traces ALTER COLUMN cost SET NOT NULL")
    op.execute("ALTER TABLE traces ALTER COLUMN tokens SET DEFAULT 0")
    op.execute("ALTER TABLE traces ALTER COLUMN cost SET DEFAULT 0")
