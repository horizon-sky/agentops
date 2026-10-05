"""评测入口：读取最近一次评测报告（M6 生成 evals/report.json）。"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends

from apps.api.src.deps import admin_user
from apps.api.src.schemas.api import EvalReportOut

router = APIRouter(prefix="/eval", tags=["eval"], dependencies=[Depends(admin_user)])

REPORT_PATH = Path("evals/report.json")


@router.get("/report", response_model=EvalReportOut)
async def get_report() -> EvalReportOut:
    if not REPORT_PATH.exists():
        return EvalReportOut(metrics={}, report_path=str(REPORT_PATH))
    data = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    return EvalReportOut(
        generated_at=datetime.now(UTC),
        metrics=data.get("metrics", {}),
        report_path=str(REPORT_PATH),
    )


@router.post("/run")
async def run_eval():
    """批量评测由本地脚本 / CI 触发，不在服务端请求内跑长任务。"""
    return {
        "ok": False,
        "detail": "评测请执行：uv run python -m evals.runner（避免占用请求时长）",
    }
