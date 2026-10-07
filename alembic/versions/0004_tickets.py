"""Persist tickets and import successful legacy snapshots."""

import logging

from alembic import op

revision = "0004_tickets"
down_revision = "0003_run_result"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE tickets (
            id uuid PRIMARY KEY,
            ticket_id varchar(64) NOT NULL,
            owner_id uuid NOT NULL REFERENCES users(id),
            run_id uuid REFERENCES runs(id) ON DELETE SET NULL,
            title varchar(300) NOT NULL,
            detail text NOT NULL DEFAULT '',
            severity varchar(2) NOT NULL DEFAULT 'P2',
            status varchar(16) NOT NULL DEFAULT 'created',
            idempotency_key varchar(200) NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            archived_at timestamptz,
            CONSTRAINT uq_tickets_owner_number UNIQUE (owner_id, ticket_id),
            CONSTRAINT uq_tickets_owner_key UNIQUE (owner_id, idempotency_key),
            CONSTRAINT ck_tickets_severity CHECK (severity IN ('P0','P1','P2','P3')),
            CONSTRAINT ck_tickets_status
                CHECK (status IN ('created','in_progress','resolved','closed'))
        );
        CREATE INDEX ix_tickets_owner_id ON tickets(owner_id);
        CREATE INDEX ix_tickets_run_id ON tickets(run_id);
    """)
    # Offline SQL cannot inspect the legacy snapshots.
    from alembic import context

    if not context.is_offline_mode():
        from src.db.ticket_backfill import backfill_tickets

        logging.getLogger("alembic.runtime.migration").info(
            "Ticket backfill: %s", backfill_tickets(op.get_bind())
        )


def downgrade() -> None:
    op.drop_table("tickets")
