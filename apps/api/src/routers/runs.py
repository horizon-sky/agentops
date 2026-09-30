"""Agent 执行入口：启动 / 订阅 SSE / 恢复（HITL）/ 中断。"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.src.deps import db_dep, require_token, settings_dep
from apps.api.src.schemas.api import CreateRunIn, OkOut, ResumeIn, RunOut
from apps.api.src.schemas.events import AgentEvent, make_event
from apps.api.src.sse import bus, sse_stream
from src.agent.runner import GraphRunner, get_runner
from src.config import Settings, get_settings
from src.db.models import Run
from src.db.session import get_session_factory

router = APIRouter(prefix="/runs", tags=["runs"], dependencies=[Depends(require_token)])

# run_id -> 后台任务，用于 abort 与进程内状态跟踪
_tasks: dict[str, asyncio.Task[None]] = {}


def _make_emit(run_id: str):
    async def emit(event: AgentEvent) -> None:
        bus.publish(event)

    return emit


@router.post("", response_model=RunOut, status_code=status.HTTP_201_CREATED)
async def create_run(
    payload: CreateRunIn,
    db: AsyncSession | None = Depends(db_dep),
    settings: Settings = Depends(settings_dep),
) -> RunOut:
    run_id = uuid.uuid4()
    if db is not None:
        run = Run(
            id=run_id,
            session_id=payload.session_id,
            query=payload.query,
            status="running",
            model_version=settings.strong_model,
            prompt_version=settings.prompt_version,
        )
        db.add(run)
        await db.commit()

    runner = get_runner(settings)

    async def _execute() -> None:
        try:
            await runner.run(str(run_id), payload.query, _make_emit(str(run_id)))
            pending = any(event.type == "hitl_request" for event in bus.history(str(run_id)))
            await _update_run(
                run_id,
                settings,
                status="awaiting_approval" if pending else "completed",
                ended=pending is False,
            )
        except Exception as exc:  # noqa: BLE001 - 异常必须转成 error 事件推给前端
            await _update_run(run_id, settings, status="failed", error_stage="generate")
            bus.publish(
                make_event(
                    type="error",
                    run_id=str(run_id),
                    stage="generate",
                    payload={"message": str(exc)[:400]},
                )
            )

    _tasks[str(run_id)] = asyncio.create_task(_execute())
    return RunOut(
        id=run_id,
        session_id=payload.session_id,
        status="running",
        model_version=settings.strong_model,
        prompt_version=settings.prompt_version,
    )


async def _update_run(
    run_id: uuid.UUID,
    settings: Settings,
    *,
    status: str,
    error_stage: str | None = None,
    ended: bool = True,
) -> None:
    factory = get_session_factory(settings)
    if factory is None:
        return
    async with factory() as db:
        run = await db.get(Run, run_id)
        if run is None:
            return
        run.status = status
        run.error_stage = error_stage
        if ended:
            run.ended_at = datetime.now(UTC)
        await db.commit()


@router.get("/{run_id}/stream")
async def stream_run(run_id: str):
    from fastapi.responses import StreamingResponse

    return StreamingResponse(
        sse_stream(run_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # 关闭 Nginx 缓冲，保证 token 实时到达
        },
    )


@router.post("/{run_id}/resume", response_model=OkOut)
async def resume_run(
    run_id: str,
    payload: ResumeIn,
    settings: Settings = Depends(settings_dep),
) -> OkOut:
    """HITL 恢复：从检查点继续执行写类工具。"""
    runner = get_runner(settings)
    if not isinstance(runner, GraphRunner):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="当前为 echo 模式，无待确认任务；设置 AGENT_MODE=graph 后可用",
        )

    async def emit(event: AgentEvent) -> None:
        bus.publish(event)

    payload_dict = {"ok": payload.ok, "args": payload.args or {}}
    if payload.comment:
        payload_dict["comment"] = payload.comment

    async def _resume() -> None:
        try:
            await runner.resume(run_id, payload_dict, emit)
            await _update_run(
                uuid.UUID(run_id), settings, status="completed" if payload.ok else "rejected"
            )
        except Exception as exc:  # noqa: BLE001
            await _update_run(uuid.UUID(run_id), settings, status="failed", error_stage="tools")
            bus.publish(
                make_event(
                    type="error",
                    run_id=run_id,
                    stage="tools",
                    payload={"message": str(exc)[:400]},
                )
            )

    _tasks[f"{run_id}:resume"] = asyncio.create_task(_resume())
    return OkOut(ok=True, detail="已提交人工确认，继续执行")


@router.post("/{run_id}/abort", response_model=OkOut)
async def abort_run(run_id: str) -> OkOut:
    task = _tasks.get(run_id)
    if task and not task.done():
        task.cancel()
        await _update_run(uuid.UUID(run_id), get_settings(), status="aborted")
        bus.publish(
            make_event(type="done", run_id=run_id, payload={"aborted": True})
        )
        return OkOut(ok=True, detail="已中断")
    return OkOut(ok=False, detail=f"未找到运行中的任务 {run_id}")


@router.get("/{run_id}/status")
async def run_status(run_id: str) -> dict[str, object]:
    task = _tasks.get(run_id)
    events = bus.history(run_id)
    persisted: dict[str, object] = {}
    settings = get_settings()
    factory = get_session_factory(settings)
    if factory is not None:
        try:
            async with factory() as db:
                run = await db.get(Run, uuid.UUID(run_id))
                if run is not None:
                    persisted = {"status": run.status, "error_stage": run.error_stage}
        except Exception:  # 数据库暂时不可用时回退到进程内状态
            pass
    current_state = str(persisted.get("status", ""))
    return {
        "run_id": run_id,
        "state": current_state or ("running" if task and not task.done() else "finished"),
        "event_count": len(events),
        "last_event_at": events[-1].ts.isoformat() if events else None,
        "checked_at": datetime.now(UTC).isoformat(),
        **persisted,
    }
