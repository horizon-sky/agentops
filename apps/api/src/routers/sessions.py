"""会话管理：创建与列表。

无数据库时仍返回可用的 session_id，保证前端链路完整可跑。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.src.deps import db_dep, require_token
from apps.api.src.schemas.api import CreateSessionIn, SessionOut
from src.db.models import Session

router = APIRouter(prefix="/sessions", tags=["sessions"], dependencies=[Depends(require_token)])


@router.post("", response_model=SessionOut)
async def create_session(
    payload: CreateSessionIn,
    db: AsyncSession | None = Depends(db_dep),
) -> SessionOut:
    if db is None:
        return SessionOut(
            id=uuid.uuid4(), title=payload.title, created_at=datetime.now(UTC)
        )
    session = Session(title=payload.title)
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return SessionOut(id=session.id, title=session.title, created_at=session.created_at)


@router.get("", response_model=list[SessionOut])
async def list_sessions(
    limit: int = 20,
    db: AsyncSession | None = Depends(db_dep),
) -> list[SessionOut]:
    if db is None:
        return []
    rows = (
        await db.execute(select(Session).order_by(Session.created_at.desc()).limit(limit))
    ).scalars().all()
    return [
        SessionOut(id=row.id, title=row.title, created_at=row.created_at) for row in rows
    ]
