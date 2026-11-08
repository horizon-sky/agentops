"""Persist structured ticket drafts separately from rendered answers."""

from alembic import op

revision = "0010_run_ticket_draft"
down_revision = "0009_run_approval_history"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE runs ADD COLUMN ticket_draft JSONB NOT NULL DEFAULT '{}'::jsonb")


def downgrade() -> None:
    op.drop_column("runs", "ticket_draft")
