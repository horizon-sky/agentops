"""Keep an append-only approval audit on each run."""

from alembic import op

revision = "0009_run_approval_history"
down_revision = "0008_auth_captchas"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE runs ADD COLUMN approval_history JSONB NOT NULL DEFAULT '[]'::jsonb")


def downgrade() -> None:
    op.drop_column("runs", "approval_history")
