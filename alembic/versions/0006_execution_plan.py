"""Persist the versioned plan, approval and per-run feature flags."""

from alembic import op

revision = "0006_execution_plan"
down_revision = "0005_retrieval_diagnostics"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for column in ("plan", "approval", "flags"):
        op.execute(f"ALTER TABLE runs ADD COLUMN {column} JSONB NOT NULL DEFAULT '{{}}'::jsonb")
    op.execute("ALTER TABLE runs ADD COLUMN contract_version INTEGER NOT NULL DEFAULT 1")


def downgrade() -> None:
    for column in ("contract_version", "flags", "approval", "plan"):
        op.drop_column("runs", column)
