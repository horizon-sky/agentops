"""指标聚合：成功率、工具准确率、延迟分位、成本、失败阶段分布。"""

from __future__ import annotations

from typing import Any


def percentile(values: list[float], ratio: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * ratio))))
    return float(ordered[index])


def aggregate(results: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(results)
    passed = sum(1 for item in results if item["passed"])
    latencies = [float(item["latency_ms"]) for item in results]
    tool_scores = [float(item["tool_accuracy"]) for item in results]
    tokens = [int(item.get("tokens", 0)) for item in results]
    cost = [float(item.get("cost_usd", 0.0)) for item in results]

    failure_stages: dict[str, int] = {}
    for item in results:
        stage = item.get("failure_stage")
        if stage:
            failure_stages[stage] = failure_stages.get(stage, 0) + 1

    skipped = sum(1 for item in results if item.get("citation_skipped"))
    return {
        "cases": total,
        "citation_skipped": skipped,
        "task_success_rate": round(passed / total * 100, 1) if total else 0.0,
        "tool_accuracy": (
            round(sum(tool_scores) / len(tool_scores) * 100, 1) if tool_scores else 0.0
        ),
        "recall_at_5": None,  # 需要标注相关 chunk 后才有意义，未标注时如实置空
        "p50_latency_ms": round(percentile(latencies, 0.5), 0),
        "p95_latency_ms": round(percentile(latencies, 0.95), 0),
        "avg_tokens": round(sum(tokens) / len(tokens), 1) if tokens else 0.0,
        "cost_per_task": round(sum(cost) / len(cost), 6) if cost else 0.0,
        "failure_stages": failure_stages,
    }


def to_markdown(metrics: dict[str, Any]) -> str:
    lines = [
        "# 评测报告",
        "",
        f"- 用例数：{metrics['cases']}",
        f"- 任务成功率：{metrics['task_success_rate']}%",
        f"- 工具准确率：{metrics['tool_accuracy']}%",
        f"- Recall@5：{metrics['recall_at_5'] if metrics['recall_at_5'] is not None else '未标注'}",
        f"- 延迟 P50 / P95：{metrics['p50_latency_ms']} ms / {metrics['p95_latency_ms']} ms",
        f"- 平均 Token：{metrics['avg_tokens']}",
        f"- 单任务成本：{metrics['cost_per_task']} USD",
        "",
        "失败阶段分布：" + (str(metrics["failure_stages"]) if metrics["failure_stages"] else "无"),
        "",
        f"引用断言跳过数：{metrics.get('citation_skipped', 0)}（无数据库时不伪造通过）",
    ]
    return "\n".join(lines)
