"""Agent 执行入口：启动 / 订阅 SSE / 恢复（HITL）/ 中断。"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.src.deps import (
    Principal,
    auth_db,
    current_user,
    owned_run,
    owned_session,
    settings_dep,
)
from apps.api.src.schemas.api import CreateRunIn, OkOut, ResumeIn, RunOut
from apps.api.src.schemas.events import AgentEvent, make_event
from apps.api.src.sse import bus, sse_stream
from src.agent.runner import GraphRunner, get_runner
from src.auth import lookup_session
from src.config import Settings
from src.db.models import Run, Session, User
from src.db.session import get_session_factory

router = APIRouter(prefix="/runs", tags=["runs"], dependencies=[Depends(current_user)])

# run_id -> 后台任务，用于 abort 与进程内状态跟踪
_tasks: dict[str, asyncio.Task[None]] = {}


async def _conversation_history(db: AsyncSession, session_id: uuid.UUID) -> list[dict[str, object]]:
    rows = (
        await db.execute(
            select(
                Run.id,
                Run.query,
                Run.answer,
                Run.status,
                Run.tool_results,
                Run.plan,
                Run.approval,
                Run.approval_history,
                Run.started_at,
            )
            .where(
                Run.session_id == session_id,
                Run.status.in_(["completed", "rejected"]),
                Run.query != "",
                Run.answer != "",
            )
            .order_by(Run.started_at.desc())
            .limit(6)
        )
    ).all()
    return [
        {
            "run_id": str(run_id),
            "query": query[:2000],
            "answer": answer[:4000],
            "answer_truncated": len(answer) > 4000,
            "status": status,
            "tool_results": tool_results or [],
            "plan": plan or {},
            "approval": approval or {},
            "approval_history": approval_history or [],
            "started_at": started_at.isoformat() if started_at else None,
        }
        for (
            run_id,
            query,
            answer,
            status,
            tool_results,
            plan,
            approval,
            approval_history,
            started_at,
        ) in reversed(rows)
    ]


def _validate_approval_text(approval: dict[str, object], payload: ResumeIn) -> None:
    if (
        approval.get("tool") == "create_ticket"
        and payload.ok
        and payload.confirmation_text != "确认创建"
    ):
        raise HTTPException(400, "创建工单必须通过后续消息单独发送“确认创建”")


async def _persist_run_result(run_id: str, settings: Settings, event: AgentEvent) -> None:
    if (
        event.type
        not in {"retrieve", "done", "plan", "hitl_request", "approval", "tool_result"}
        or not event.payload
    ):
        return
    factory = get_session_factory(settings)
    if factory is None:
        return
    try:
        async with factory() as db:
            run = await db.scalar(select(Run).where(Run.id == uuid.UUID(run_id)))
            if run is None:
                return
            payload = event.payload
            for field in ("answer", "citations", "retrieval", "plan"):
                if field in payload:
                    setattr(run, field, payload[field])
            if "tools" in payload:
                run.tool_results = payload["tools"]
            if event.type == "hitl_request":
                run.approval = payload
                history = list(run.approval_history or [])
                history.append(
                    {
                        "event": "requested",
                        "event_id": event.id,
                        "at": event.ts.isoformat(),
                        "approval_id": payload.get("approval_id"),
                        "step_id": payload.get("step_id"),
                        "tool": payload.get("tool"),
                        "args": payload.get("args", {}),
                    }
                )
                run.approval_history = history
            if event.type == "approval":
                history = list(run.approval_history or [])
                history.append(
                    {
                        **payload,
                        "event_id": event.id,
                        "at": event.ts.isoformat(),
                    }
                )
                run.approval_history = history
            if event.type == "tool_result":
                run.tool_results = [
                    result
                    for result in (run.tool_results or [])
                    if result.get("step_id") != payload.get("step_id")
                ] + [payload]
                if payload.get("risk") == "high":
                    history = list(run.approval_history or [])
                    history.append(
                        {
                            "event": "executed",
                            "event_id": event.id,
                            "at": event.ts.isoformat(),
                            "approval_id": f"{run_id}:{payload.get('step_id')}",
                            "step_id": payload.get("step_id"),
                            "tool": payload.get("name"),
                            "ok": payload.get("ok"),
                            "args": payload.get("args", {}),
                            "output": payload.get("output"),
                            "error": payload.get("error"),
                        }
                    )
                    run.approval_history = history
                if (run.approval or {}).get("step_id") == payload.get("step_id"):
                    run.approval = {}
            if event.type == "done":
                run.approval = {}
            await db.commit()
    except Exception:
        # 结果快照失败不应中断 SSE；运行状态仍由 _execute 收敛。
        return


def _make_emit(run_id: str, settings: Settings):
    async def emit(event: AgentEvent) -> None:
        bus.publish(event)
        await _persist_run_result(run_id, settings, event)

    return emit


@router.post("", response_model=RunOut, status_code=status.HTTP_201_CREATED)
async def create_run(
    payload: CreateRunIn,
    db: AsyncSession = Depends(auth_db),
    settings: Settings = Depends(settings_dep),
    identity: Principal = Depends(current_user),
) -> RunOut:
    if not settings.accept_new_runs:
        raise HTTPException(503, "任务契约升级中，暂不接收新任务")
    await owned_session(db, payload.session_id, identity.user.id)
    conversation_history = await _conversation_history(db, payload.session_id)
    # Serialize admissions per user so concurrent requests cannot bypass the quota.
    await db.execute(select(User.id).where(User.id == identity.user.id).with_for_update())
    user_runs = (
        select(func.count())
        .select_from(Run)
        .join(Session)
        .where(Session.owner_id == identity.user.id)
    )
    active = await db.scalar(user_runs.where(Run.status.in_(["running", "awaiting_approval"])))
    day_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    daily = await db.scalar(user_runs.where(Run.started_at >= day_start))
    if (active or 0) >= settings.max_active_runs_per_user:
        raise HTTPException(429, "同时执行或等待审批的任务已达到上限")
    if (daily or 0) >= settings.max_runs_per_user_per_day:
        raise HTTPException(429, "今日任务额度已用完")
    run_id = uuid.uuid4()
    run = Run(
        id=run_id,
        session_id=payload.session_id,
        query=payload.query,
        status="running",
        model_version=settings.strong_model,
        prompt_version=settings.prompt_version,
        flags=settings.agent_flags(),
    )
    db.add(run)
    await db.commit()
    user_id = str(identity.user.id)
    runner = get_runner(settings)

    async def _execute() -> None:
        try:
            await runner.run(
                str(run_id),
                payload.query,
                _make_emit(str(run_id), settings),
                user_id=user_id,
                conversation_history=conversation_history,
            )
            pending = isinstance(runner, GraphRunner) and await runner.awaiting_approval(
                str(run_id)
            )
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
        query=payload.query,
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
        run = await db.scalar(select(Run).where(Run.id == run_id).with_for_update())
        if run is None or run.status == "aborted":
            return
        if status == "completed" and any(r.get("denied") for r in (run.tool_results or [])):
            status = "rejected"
        run.status = status
        run.error_stage = error_stage
        if ended:
            run.ended_at = datetime.now(UTC)
        await db.commit()


@router.get("/{run_id}/stream")
async def stream_run(
    run_id: uuid.UUID,
    db: AsyncSession = Depends(auth_db),
    identity: Principal = Depends(current_user),
    settings: Settings = Depends(settings_dep),
):
    from fastapi.responses import StreamingResponse

    await owned_run(db, run_id, identity.user.id)
    await db.rollback()  # The stream uses short independent DB transactions.

    async def authorized() -> bool:
        factory = get_session_factory(settings)
        if factory is None:
            return False
        try:
            async with factory() as check_db:
                return await lookup_session(check_db, identity.token) is not None
        except Exception:
            return False  # Fail closed when the session store is unavailable.

    return StreamingResponse(
        sse_stream(str(run_id), authorized=authorized),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # 关闭 Nginx 缓冲，保证 token 实时到达
        },
    )


@router.post("/{run_id}/resume", response_model=OkOut)
async def resume_run(
    run_id: uuid.UUID,
    payload: ResumeIn,
    settings: Settings = Depends(settings_dep),
    db: AsyncSession = Depends(auth_db),
    identity: Principal = Depends(current_user),
) -> OkOut:
    """HITL 恢复：从检查点继续执行写类工具。"""
    run = await owned_run(db, run_id, identity.user.id, lock=True)
    if run.status != "awaiting_approval":
        raise HTTPException(409, "当前任务没有待确认操作")
    flags = run.flags or {}
    settings = (
        settings.model_copy(
            update={
                "agent_mode": flags.get("mode", settings.agent_mode),
                "agent_conditional_routing": flags.get(
                    "routing", settings.agent_conditional_routing
                ),
                "agent_targeted_retry": flags.get("retry", settings.agent_targeted_retry),
                "agent_dynamic_plan": flags.get("dynamic", settings.agent_dynamic_plan),
            }
        )
        if flags
        else settings
    )
    runner = get_runner(settings)
    if not isinstance(runner, GraphRunner):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="当前为 echo 模式，无待确认任务；设置 AGENT_MODE=graph 后可用",
        )

    if not payload.approval_id or payload.approval_id != (run.approval or {}).get("approval_id"):
        raise HTTPException(409, "审批已过期或与当前操作不匹配")
    _validate_approval_text(run.approval or {}, payload)

    approval = run.approval or {}
    approved_args = {**approval.get("args", {}), **(payload.args or {})}
    history = list(run.approval_history or [])
    history.append(
        {
            "event": "decision",
            "at": datetime.now(UTC).isoformat(),
            "approval_id": payload.approval_id,
            "step_id": approval.get("step_id"),
            "tool": approval.get("tool"),
            "ok": payload.ok,
            "actor_id": str(identity.user.id),
            "confirmation_text": payload.confirmation_text,
            "args": approved_args,
            "comment": payload.comment,
        }
    )
    run.approval_history = history

    payload_dict = {
        "ok": payload.ok,
        "args": payload.args or {},
        "approval_id": payload.approval_id,
    }
    if payload.comment:
        payload_dict["comment"] = payload.comment
    run.status = "running"
    await db.commit()
    user_id = str(identity.user.id)

    async def emit(event: AgentEvent) -> None:
        bus.publish(event)
        await _persist_run_result(str(run_id), settings, event)

    async def _resume() -> None:
        try:
            await runner.resume(str(run_id), payload_dict, emit, user_id=user_id)
            pending = await runner.awaiting_approval(str(run_id))
            await _update_run(
                run_id,
                settings,
                status="awaiting_approval" if pending else "completed",
                ended=not pending,
            )
        except Exception as exc:  # noqa: BLE001
            await _update_run(run_id, settings, status="failed", error_stage="tools")
            bus.publish(
                make_event(
                    type="error",
                    run_id=str(run_id),
                    stage="tools",
                    payload={"message": str(exc)[:400]},
                )
            )

    _tasks[f"{run_id}:resume"] = asyncio.create_task(_resume())
    return OkOut(ok=True, detail="已提交人工确认，继续执行")


@router.post("/{run_id}/abort", response_model=OkOut)
async def abort_run(
    run_id: uuid.UUID,
    db: AsyncSession = Depends(auth_db),
    identity: Principal = Depends(current_user),
) -> OkOut:
    run = await owned_run(db, run_id, identity.user.id, lock=True)
    task = _tasks.get(f"{run_id}:resume") or _tasks.get(str(run_id))
    if task and not task.done():
        task.cancel()
        # Commit with the existing lock, rather than deadlocking a second transaction.
        run.status = "aborted"
        run.ended_at = datetime.now(UTC)
        await db.commit()
        bus.publish(make_event(type="done", run_id=str(run_id), payload={"aborted": True}))
        return OkOut(ok=True, detail="已中断")
    if run.status in {"running", "awaiting_approval"}:
        run.status = "aborted"
        run.ended_at = datetime.now(UTC)
        await db.commit()
        bus.publish(make_event(type="done", run_id=str(run_id), payload={"aborted": True}))
        return OkOut(ok=True, detail="已中断")
    return OkOut(ok=False, detail="任务已经结束")


@router.get("/{run_id}/status")
async def run_status(
    run_id: uuid.UUID,
    db: AsyncSession = Depends(auth_db),
    identity: Principal = Depends(current_user),
) -> dict[str, object]:
    run = await owned_run(db, run_id, identity.user.id)
    events = bus.history(str(run_id))
    count = len(events)
    last_at = events[-1].ts.isoformat() if events else None
    return {
        "run_id": str(run_id),
        "state": run.status,
        "status": run.status,
        "error_stage": run.error_stage,
        "event_count": count,
        "last_event_at": last_at,
        "checked_at": datetime.now(UTC).isoformat(),
    }
