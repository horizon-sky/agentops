"""当前用户的会话创建与列表。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.src.deps import Principal, auth_db, current_user
from apps.api.src.schemas.api import CreateSessionIn, SessionOut
from src.db.models import Session

router = APIRouter(prefix="/sessions", tags=["sessions"], dependencies=[Depends(current_user)])


@router.post("", response_model=SessionOut)
async def create_session(
    payload: CreateSessionIn,
    db: AsyncSession = Depends(auth_db),
    identity: Principal = Depends(current_user),
) -> SessionOut:
    session = Session(title=payload.title, owner_id=identity.user.id)
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return SessionOut(id=session.id, title=session.title, created_at=session.created_at)


@router.get("", response_model=list[SessionOut])
async def list_sessions(
    limit: int = 20,
    db: AsyncSession = Depends(auth_db),
    identity: Principal = Depends(current_user),
) -> list[SessionOut]:
    rows = (
        await db.execute(
            select(Session).where(Session.owner_id == identity.user.id)
            .order_by(Session.created_at.desc()).limit(max(1, min(limit, 100)))
        )
    ).scalars().all()
    return [
        SessionOut(id=row.id, title=row.title, created_at=row.created_at) for row in rows
    ]
