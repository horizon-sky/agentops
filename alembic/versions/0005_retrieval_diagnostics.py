"""Persist retrieval diagnostics alongside answer snapshots."""

from alembic import op

revision = "0005_retrieval_diagnostics"
down_revision = "0004_tickets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE runs ADD COLUMN retrieval JSONB NOT NULL DEFAULT '{}'::jsonb")


def downgrade() -> None:
    op.drop_column("runs", "retrieval")
