"""Persist completed evaluation times and public provenance without changing legacy rows."""

from alembic import op

revision = "0007_eval_reports"
down_revision = "0006_execution_plan"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE eval_runs ADD COLUMN generated_at TIMESTAMPTZ")
    op.execute("ALTER TABLE eval_runs ADD COLUMN source JSONB NOT NULL DEFAULT '{}'::jsonb")
    op.execute("CREATE INDEX ix_eval_runs_generated_at ON eval_runs (generated_at DESC, id DESC)")


def downgrade() -> None:
    op.drop_index("ix_eval_runs_generated_at", table_name="eval_runs")
    op.drop_column("eval_runs", "source")
    op.drop_column("eval_runs", "generated_at")
