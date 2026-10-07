"""Persisted tickets; the database is the source of truth for idempotency."""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import Run, Session, Ticket, User

Severity = Literal["P0", "P1", "P2", "P3"]
TicketStatus = Literal["created", "in_progress", "resolved", "closed"]


class TicketFields(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    title: str = Field(min_length=1, max_length=300)
    detail: str = Field(default="", max_length=20000)
    severity: Severity = "P2"


async def persist_ticket(
    db: AsyncSession,
    *,
    owner_id: uuid.UUID,
    run_id: uuid.UUID,
    fields: TicketFields,
    idempotency_key: str,
) -> Ticket:
    # The same lock serializes concurrent creates for a user, including retries.
    owner = await db.scalar(
        select(User)
        .where(User.id == owner_id, User.is_active.is_(True), User.verified_at.is_not(None))
        .with_for_update()
    )
    run = await db.scalar(
        select(Run).join(Session).where(Run.id == run_id, Session.owner_id == owner_id)
    )
    if owner is None or run is None:
        raise PermissionError("Ticket creation requires an owned run and verified user")
    ticket = await db.scalar(
        select(Ticket).where(Ticket.owner_id == owner_id, Ticket.idempotency_key == idempotency_key)
    )
    if ticket is not None:
        if ticket.archived_at is not None:
            raise ValueError("The ticket for this operation has been archived")
        return ticket
    ticket_uuid = uuid.uuid4()
    ticket = Ticket(
        id=ticket_uuid,
        ticket_id=f"OPS-{ticket_uuid.hex}",
        owner_id=owner_id,
        run_id=run_id,
        idempotency_key=idempotency_key,
        **fields.model_dump(),
    )
    db.add(ticket)
    await db.commit()
    await db.refresh(ticket)
    return ticket
