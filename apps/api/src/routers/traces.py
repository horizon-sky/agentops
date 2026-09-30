"""Trace 查询：优先读数据库 span 树，无数据库时回退到事件总线历史。"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.src.deps import db_dep, require_token
from apps.api.src.schemas.api import TraceNode
from apps.api.src.sse import bus
from src.db.models import Trace

router = APIRouter(prefix="/traces", tags=["traces"], dependencies=[Depends(require_token)])


@router.get("/{run_id}", response_model=list[TraceNode])
async def get_trace(
    run_id: str,
    db: AsyncSession | None = Depends(db_dep),
) -> list[TraceNode]:
    if db is not None:
        try:
            run_uuid = uuid.UUID(run_id)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="非法 run_id"
            ) from exc
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

    # 无数据库：把事件历史折叠成线性 span，仍可在前端回放
    events = bus.history(run_id)
    return [
        TraceNode(
            id=uuid.uuid4(),
            stage=event.stage or "plan",
            name=event.type,
            status="error" if event.type == "error" else "ok",
            ms=event.ms or 0,
            inputs={"payload": event.payload or {}},
        )
        for event in events
    ]
