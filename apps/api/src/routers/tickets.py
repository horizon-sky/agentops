"""User-owned ticket overview, editing and archival."""

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.src.deps import Principal, auth_db, current_user
from apps.api.src.schemas.api import OkOut
from src.db.models import Ticket
from src.tickets import TicketFields, TicketStatus

router = APIRouter(prefix="/tickets", tags=["tickets"])


class TicketUpdate(TicketFields):
    status: TicketStatus


class TicketOut(TicketFields):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    ticket_id: str
    status: TicketStatus
    created_at: datetime
    updated_at: datetime


class TicketPage(BaseModel):
    items: list[TicketOut]
    total: int
    page: int
    page_size: int = 20


async def owned_ticket(db: AsyncSession, ticket_id: UUID, user_id: UUID) -> Ticket:
    ticket = await db.scalar(
        select(Ticket)
        .where(Ticket.id == ticket_id, Ticket.owner_id == user_id, Ticket.archived_at.is_(None))
        .with_for_update()
    )
    if ticket is None:
        raise HTTPException(404, "工单不存在")
    return ticket


@router.get("", response_model=TicketPage)
async def list_tickets(
    page: int = Query(default=1, ge=1),
    identity: Principal = Depends(current_user),
    db: AsyncSession = Depends(auth_db),
) -> TicketPage:
    scope = (Ticket.owner_id == identity.user.id, Ticket.archived_at.is_(None))
    total = await db.scalar(select(func.count()).select_from(Ticket).where(*scope)) or 0
    tickets = await db.scalars(
        select(Ticket)
        .where(*scope)
        .order_by(Ticket.created_at.desc(), Ticket.id.desc())
        .offset((page - 1) * 20)
        .limit(20)
    )
    return TicketPage(items=[TicketOut.model_validate(t) for t in tickets], total=total, page=page)


@router.patch("/{ticket_id}", response_model=TicketOut)
async def update_ticket(
    ticket_id: UUID,
    payload: TicketUpdate,
    identity: Principal = Depends(current_user),
    db: AsyncSession = Depends(auth_db),
) -> TicketOut:
    ticket = await owned_ticket(db, ticket_id, identity.user.id)
    for field, value in payload.model_dump().items():
        setattr(ticket, field, value)
    ticket.updated_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(ticket)
    return TicketOut.model_validate(ticket)


@router.delete("/{ticket_id}", response_model=OkOut)
async def archive_ticket(
    ticket_id: UUID,
    identity: Principal = Depends(current_user),
    db: AsyncSession = Depends(auth_db),
) -> OkOut:
    ticket = await owned_ticket(db, ticket_id, identity.user.id)
    ticket.archived_at = ticket.updated_at = datetime.now(UTC)
    await db.commit()
    return OkOut(ok=True)
