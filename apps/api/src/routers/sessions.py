"""当前用户的会话创建与列表。"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.src.deps import Principal, auth_db, current_user, owned_session
from apps.api.src.schemas.api import CreateSessionIn, RunOut, SessionOut
from src.db.models import Run, Session

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


@router.get("/{session_id}/runs", response_model=list[RunOut])
async def list_session_runs(
    session_id: str,
    db: AsyncSession = Depends(auth_db),
    identity: Principal = Depends(current_user),
) -> list[RunOut]:
    """返回会话运行快照，供刷新后恢复最后一次 Agent 输出。"""
    try:
        session_uuid = uuid.UUID(session_id)
    except ValueError as exc:
        raise HTTPException(404, "会话不存在") from exc
    await owned_session(db, session_uuid, identity.user.id)
    rows = (
        await db.execute(
            select(Run)
            .where(Run.session_id == session_uuid)
            .order_by(Run.started_at.desc())
            .limit(20)
        )
    ).scalars().all()
    return [
        RunOut(
            id=row.id,
            session_id=row.session_id,
            status=row.status,
            model_version=row.model_version,
            prompt_version=row.prompt_version,
            query=row.query,
            answer=row.answer,
            citations=row.citations or [],
            retrieval=row.retrieval or {},
            tool_results=row.tool_results or [],
            ended_at=row.ended_at,
        )
        for row in rows
    ]
