"""管理员评测入口：读取已发布的数据库汇总报告。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.src.deps import admin_user, auth_db
from apps.api.src.schemas.api import EvalReportOut
from src.db import eval_reports

router = APIRouter(prefix="/eval", tags=["eval"], dependencies=[Depends(admin_user)])

@router.get("/report", response_model=EvalReportOut)
async def get_report(db: AsyncSession = Depends(auth_db)) -> EvalReportOut:
    try:
        report = await eval_reports.latest_report(db)
    except SQLAlchemyError as exc:
        raise HTTPException(503, "评测报告暂时无法读取，请稍后重试") from exc
    if report is None:
        return EvalReportOut()
    return EvalReportOut(
        status="ready", id=report.id, started_at=report.started_at,
        generated_at=report.generated_at, metrics=report.metrics, source=report.source,
        git_sha=report.git_sha, prompt_version=report.prompt_version,
        model_version=report.model_version,
    )


@router.post("/run")
async def run_eval():
    """批量评测由本地脚本 / CI 触发，不在服务端请求内跑长任务。"""
    return {
        "ok": False,
        "detail": "评测请执行：uv run python -m evals.runner（避免占用请求时长）",
    }
