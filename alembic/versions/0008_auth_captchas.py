"""Short-lived, single-attempt registration image challenges."""

from alembic import op

revision = "0008_auth_captchas"
down_revision = "0007_eval_reports"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE auth_captchas (
            id uuid PRIMARY KEY,
            answer_hash varchar(64) NOT NULL,
            expires_at timestamptz NOT NULL
        );
        CREATE INDEX ix_auth_captchas_expires_at ON auth_captchas(expires_at);
    """)


def downgrade() -> None:
    op.drop_table("auth_captchas")
