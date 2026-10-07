"""Persist completed run output for refresh and replay."""

from alembic import op

revision = "0003_run_result"
down_revision = "0002_accounts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE runs ADD COLUMN answer text NOT NULL DEFAULT ''")
    op.execute("ALTER TABLE runs ADD COLUMN citations jsonb NOT NULL DEFAULT '[]'::jsonb")
    op.execute("ALTER TABLE runs ADD COLUMN tool_results jsonb NOT NULL DEFAULT '[]'::jsonb")


def downgrade() -> None:
    op.execute("ALTER TABLE runs DROP COLUMN tool_results")
    op.execute("ALTER TABLE runs DROP COLUMN citations")
    op.execute("ALTER TABLE runs DROP COLUMN answer")
