"""评测执行器：直接调用 graph（不经 HTTP），逐条断言并生成报告。

用法：
    uv run python -m evals.runner                 # 全量 120 条
    uv run python -m evals.runner --limit 20      # 分批跑（推荐，便于中断续跑）
    uv run python -m evals.runner --offset 20

说明：所有指标均为真实运行结果；Recall@5 需要先标注相关 chunk，未标注时置空。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter

from apps.api.src.schemas.events import AgentEvent
from evals.judges import judge
from evals.metrics import aggregate, to_markdown
from src.agent.runner import GraphRunner
from src.config import Settings, get_settings
from src.db.models import Run, Session, User
from src.db.session import get_session_factory

ROOT = Path(__file__).resolve().parent
GOLDEN = ROOT / "golden_set.json"
REPORT_JSON = ROOT / "report.json"
REPORT_MD = ROOT / "report.md"


def _run(coro: object) -> int:
    """Windows 的 psycopg 异步连接池需要 SelectorEventLoop。"""
    if sys.platform == "win32":
        policy = getattr(asyncio, "WindowsSelectorEventLoopPolicy", None)
        if policy is not None:
            asyncio.set_event_loop_policy(policy())
    return asyncio.run(coro)  # type: ignore[arg-type]


class Collector:
    def __init__(self) -> None:
        self.intent: str | None = None
        self.tools: list[str] = []
        self.retrieve_hits = 0
        self.citations = 0
        self.hitl = False
        self.answer = ""
        self.tokens = 0
        self.approval: dict[str, object] = {}
        self.approval_count = 0
        self.retry_count = 0
        self.events: list[str] = []

    async def __call__(self, event: AgentEvent) -> None:
        payload = event.payload or {}
        self.events.append(event.type)
        if event.type == "plan":
            self.retry_count = max(self.retry_count, int(payload.get("review", {}).get("retry", 0)))
            if isinstance(payload.get("intent"), str):
                self.intent = payload["intent"]
        elif event.type == "retrieve":
            self.retrieve_hits = int(payload.get("hits", 0) or 0)
            citations = payload.get("citations")
            if isinstance(citations, list):
                self.citations = len(citations)
        elif event.type == "tool_result":
            name = payload.get("name")
            if isinstance(name, str):
                self.tools.append(name)
        elif event.type == "hitl_request":
            self.hitl = True
            self.approval = payload
            self.approval_count += 1
        elif event.type == "done":
            self.answer = str(payload.get("answer", "") or "")
            citations = payload.get("citations")
            if isinstance(citations, list):
                self.citations = max(self.citations, len(citations))


async def _create_eval_run(run_id: str, query: str, settings: Settings, user_id: str = "") -> None:
    factory = get_session_factory(settings)
    if factory is None:
        return
    if not user_id:
        raise ValueError("Database evaluation requires --user-id for a verified account")
    async with factory() as db:
        user = await db.get(User, uuid.UUID(user_id))
        if user is None or not user.is_active or user.verified_at is None:
            raise ValueError("Evaluation account must be active and verified")
        session = Session(title="评测运行", owner_id=user.id)
        db.add(session)
        await db.flush()
        db.add(
            Run(
                id=uuid.UUID(run_id),
                session_id=session.id,
                query=query,
                status="running",
                model_version=settings.strong_model,
                prompt_version=settings.prompt_version,
            )
        )
        await db.commit()


async def _finish_eval_run(run_id: str, settings: Settings, status: str) -> None:
    factory = get_session_factory(settings)
    if factory is None:
        return
    async with factory() as db:
        run = await db.get(Run, uuid.UUID(run_id))
        if run is None:
            return
        run.status = status
        run.ended_at = datetime.now(UTC)
        await db.commit()


async def run_case(
    case: dict[str, object], runner: GraphRunner, settings: Settings, user_id: str = ""
) -> dict[str, object]:
    collector = Collector()
    run_id = str(uuid.uuid4())
    started = perf_counter()

    pending = None
    if case.get("expect_hitl"):
        title = str(case["query"])[:40]
        pending = [
            {"name": "search_code", "args": {"query": title}},
            {"name": "create_ticket", "args": {"title": title, "severity": "P1"}},
        ]

    await _create_eval_run(run_id, str(case["query"]), settings, user_id)
    try:
        await runner.run(
            run_id, str(case["query"]), collector, pending_calls=pending, user_id=user_id
        )
        while await runner.awaiting_approval(run_id):  # 评测中模拟人工审批通过
            approve_args = {
                "ok": True,
                "args": {"title": str(case["query"])[:40]},
                "approval_id": collector.approval.get("approval_id"),
            }
            await runner.resume(run_id, approve_args, collector, user_id=user_id)
    except Exception:
        await _finish_eval_run(run_id, settings, "failed")
        raise
    await _finish_eval_run(run_id, settings, "completed")

    latency_ms = int((perf_counter() - started) * 1000)
    verdict = judge(
        case,  # type: ignore[arg-type]
        {
            "intent": collector.intent,
            "tools": collector.tools,
            "retrieve_hits": collector.retrieve_hits,
            "citations": collector.citations,
            "hitl": collector.hitl,
            "answer": collector.answer,
            "approval_count": collector.approval_count,
            "retry_count": collector.retry_count,
            "events": collector.events,
        },
        db_available=settings.has_database,
    )
    return {
        "id": case["id"],
        "query": case["query"],
        "latency_ms": latency_ms,
        "tokens": collector.tokens,
        "cost_usd": 0.0,
        **verdict,
    }


async def main(limit: int | None, offset: int, user_id: str = "") -> int:
    data = json.loads(GOLDEN.read_text(encoding="utf-8"))
    cases = data["cases"][offset:]
    if limit:
        cases = cases[:limit]

    settings = get_settings()
    runner = GraphRunner(settings)
    results: list[dict[str, object]] = []

    for case in cases:
        results.append(await run_case(case, runner, settings, user_id))
        print(f"{case['id']} {'PASS' if results[-1]['passed'] else 'FAIL'}")

    metrics = aggregate([item for item in results if isinstance(item, dict)])  # type: ignore[arg-type]
    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "golden_set_version": data["version"],
        "metrics": metrics,
        "results": results,
    }
    REPORT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    REPORT_MD.write_text(to_markdown(metrics), encoding="utf-8")
    print(to_markdown(metrics))
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--user-id", default="", help="Verified account owning evaluation data")
    args = parser.parse_args()
    raise SystemExit(_run(main(args.limit, args.offset, args.user_id)))
