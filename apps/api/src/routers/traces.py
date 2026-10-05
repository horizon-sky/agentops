"""查询当前用户运行的 span 树。"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.src.deps import Principal, auth_db, current_user, owned_run
from apps.api.src.schemas.api import TraceNode
from src.db.models import Trace

router = APIRouter(prefix="/traces", tags=["traces"], dependencies=[Depends(current_user)])


@router.get("/{run_id}", response_model=list[TraceNode])
async def get_trace(
    run_id: str,
    db: AsyncSession = Depends(auth_db),
    identity: Principal = Depends(current_user),
) -> list[TraceNode]:
    try:
        run_uuid = uuid.UUID(run_id)
    except ValueError as exc:
        raise HTTPException(404, "运行不存在") from exc
    await owned_run(db, run_uuid, identity.user.id)
    rows = (
        await db.execute(
            select(Trace).where(Trace.run_id == run_uuid).order_by(Trace.created_at)
        )
    ).scalars().all()
    nodes = {
        row.id: TraceNode(
            id=row.id,
            stage=row.stage,
            name=row.name,
            status=row.status,
            ms=row.ms,
            tokens=row.tokens,
            cost=float(row.cost or 0),
            inputs=row.inputs or {},
            outputs=row.outputs or {},
        )
        for row in rows
    }
    roots: list[TraceNode] = []
    for row in rows:
        node = nodes[row.id]
        parent = nodes.get(row.parent_id) if row.parent_id else None
        if parent is None:
            roots.append(node)
        else:
            parent.children.append(node)
    return roots
