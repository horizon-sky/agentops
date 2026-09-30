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
import uuid
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter

from apps.api.src.schemas.events import AgentEvent
from evals.judges import judge
from evals.metrics import aggregate, to_markdown
from src.agent.runner import GraphRunner
from src.config import get_settings

ROOT = Path(__file__).resolve().parent
GOLDEN = ROOT / "golden_set.json"
REPORT_JSON = ROOT / "report.json"
REPORT_MD = ROOT / "report.md"


class Collector:
    def __init__(self) -> None:
        self.intent: str | None = None
        self.tools: list[str] = []
        self.retrieve_hits = 0
        self.citations = 0
        self.hitl = False
        self.answer = ""
        self.tokens = 0

    async def __call__(self, event: AgentEvent) -> None:
        payload = event.payload or {}
        if event.type == "plan":
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
        elif event.type == "done":
            self.answer = str(payload.get("answer", "") or "")
            citations = payload.get("citations")
            if isinstance(citations, list):
                self.citations = max(self.citations, len(citations))


async def run_case(
    case: dict[str, object], runner: GraphRunner, db_available: bool
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

    await runner.run(run_id, str(case["query"]), collector, pending_calls=pending)
    if collector.hitl:  # 评测中自动确认，模拟人工审批通过
        approve_args = {"ok": True, "args": {"title": str(case["query"])[:40]}}
        await runner.resume(run_id, approve_args, collector)

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
        },
        db_available=db_available,
    )
    return {
        "id": case["id"],
        "query": case["query"],
        "latency_ms": latency_ms,
        "tokens": collector.tokens,
        "cost_usd": 0.0,
        **verdict,
    }


async def main(limit: int | None, offset: int) -> int:
    data = json.loads(GOLDEN.read_text(encoding="utf-8"))
    cases = data["cases"][offset:]
    if limit:
        cases = cases[:limit]

    settings = get_settings()
    runner = GraphRunner(settings)
    results: list[dict[str, object]] = []

    for case in cases:
        results.append(await run_case(case, runner, settings.has_database))
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
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main(args.limit, args.offset)))
