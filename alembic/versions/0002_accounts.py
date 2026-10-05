"""Accounts, revocable authentication sessions and private resource ownership."""

from alembic import op

revision = "0002_accounts"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE users (
            id uuid PRIMARY KEY, email varchar(254) NOT NULL UNIQUE,
            password_hash text NOT NULL, display_name varchar(80) NOT NULL,
            role varchar(16) NOT NULL DEFAULT 'member', is_active boolean NOT NULL DEFAULT true,
            verified_at timestamptz, created_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE TABLE auth_sessions (
            id uuid PRIMARY KEY, user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            token_hash varchar(64) NOT NULL UNIQUE, expires_at timestamptz NOT NULL,
            revoked_at timestamptz, created_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX ix_auth_sessions_user_id ON auth_sessions(user_id);
        CREATE INDEX ix_auth_sessions_expires_at ON auth_sessions(expires_at);
        CREATE TABLE auth_tokens (
            id uuid PRIMARY KEY, user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            purpose varchar(16) NOT NULL, token_hash varchar(64) NOT NULL UNIQUE,
            expires_at timestamptz NOT NULL, used_at timestamptz
        );
        CREATE INDEX ix_auth_tokens_user_id ON auth_tokens(user_id);
        CREATE INDEX ix_auth_tokens_expires_at ON auth_tokens(expires_at);

        -- Legacy data belongs to a disabled archive account, never to a public signup.
        INSERT INTO users (id, email, password_hash, display_name, role, is_active)
        VALUES ('00000000-0000-0000-0000-000000000001', 'archive@agentops.invalid',
                'disabled', '历史数据归档', 'admin', false);
        ALTER TABLE sessions ADD COLUMN owner_id uuid REFERENCES users(id);
        UPDATE sessions SET owner_id = '00000000-0000-0000-0000-000000000001';
        ALTER TABLE sessions ALTER COLUMN owner_id SET NOT NULL;
        CREATE INDEX ix_sessions_owner_id ON sessions(owner_id);
        ALTER TABLE documents ADD COLUMN owner_id uuid REFERENCES users(id);
        UPDATE documents SET owner_id = '00000000-0000-0000-0000-000000000001';
        ALTER TABLE documents ALTER COLUMN owner_id SET NOT NULL;
        CREATE INDEX ix_documents_owner_id ON documents(owner_id);
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE documents DROP COLUMN owner_id;
        ALTER TABLE sessions DROP COLUMN owner_id;
        DROP TABLE auth_tokens, auth_sessions, users;
    """)
