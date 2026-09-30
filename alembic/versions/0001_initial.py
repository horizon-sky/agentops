"""create initial AgentOps schema"""
# ruff: noqa: E501

from alembic import op

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("""
        CREATE TABLE sessions (
            id uuid PRIMARY KEY, title varchar(200) NOT NULL DEFAULT '新会话',
            created_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE TABLE runs (
            id uuid PRIMARY KEY, session_id uuid NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
            query text NOT NULL DEFAULT '', status varchar(32) NOT NULL DEFAULT 'created',
            model_version varchar(64) NOT NULL DEFAULT '', prompt_version varchar(64) NOT NULL DEFAULT '',
            error_stage varchar(32), started_at timestamptz NOT NULL DEFAULT now(), ended_at timestamptz
        );
        CREATE TABLE documents (
            id uuid PRIMARY KEY, title varchar(300) NOT NULL DEFAULT '', source varchar(500) NOT NULL DEFAULT '',
            version varchar(64) NOT NULL DEFAULT 'v1', created_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE TABLE chunks (
            id uuid PRIMARY KEY, document_id uuid NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
            chunk_id varchar(64) NOT NULL, seq integer NOT NULL DEFAULT 0, content text NOT NULL DEFAULT '',
            token_count integer NOT NULL DEFAULT 0, tsv tsvector, embedding vector, meta jsonb NOT NULL DEFAULT '{}'::jsonb
        );
        CREATE TABLE traces (
            id uuid PRIMARY KEY, run_id uuid NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
            parent_id uuid, stage varchar(32) NOT NULL DEFAULT '', name varchar(120) NOT NULL DEFAULT '',
            status varchar(32) NOT NULL DEFAULT 'ok', ms integer NOT NULL DEFAULT 0, tokens integer NOT NULL DEFAULT 0,
            cost integer NOT NULL DEFAULT 0, inputs jsonb NOT NULL DEFAULT '{}'::jsonb,
            outputs jsonb NOT NULL DEFAULT '{}'::jsonb, created_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE TABLE eval_runs (
            id uuid PRIMARY KEY, git_sha varchar(64) NOT NULL DEFAULT '', prompt_version varchar(64) NOT NULL DEFAULT '',
            model_version varchar(64) NOT NULL DEFAULT '', metrics jsonb NOT NULL DEFAULT '{}'::jsonb,
            report_path varchar(300) NOT NULL DEFAULT '', started_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX ix_runs_session_id ON runs(session_id);
        CREATE INDEX ix_runs_status ON runs(status);
        CREATE INDEX ix_chunks_document_id ON chunks(document_id);
        CREATE INDEX ix_chunks_chunk_id ON chunks(chunk_id);
        CREATE INDEX ix_chunks_tsv ON chunks USING gin(tsv);
        CREATE INDEX ix_traces_run_id ON traces(run_id);
        CREATE INDEX ix_traces_parent_id ON traces(parent_id);
        CREATE INDEX ix_traces_stage ON traces(stage);
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS eval_runs, traces, chunks, documents, runs, sessions CASCADE")
