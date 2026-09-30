"""内置工具实现（进程内执行；同名能力同时以 MCP Server 形态提供）。

数据说明：
- search_code 对本仓库 src/ 做真实文本检索；
- query_metrics / create_ticket 使用 data/ 下的样例数据，属演示数据源，
  README 与简历中均如实标注，不冒充真实生产系统。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"


class SearchCodeArgs(BaseModel):
    query: str = Field(description="检索关键字或错误信息")
    top_k: int = Field(default=5, ge=1, le=20)


class QueryMetricsArgs(BaseModel):
    service: str = Field(default="order-service", description="服务名")
    window: str = Field(default="1h", description="时间窗口，如 15m / 1h / 24h")


class CreateTicketArgs(BaseModel):
    title: str = Field(description="工单标题")
    detail: str = Field(default="", description="工单描述")
    severity: str = Field(default="P2", description="P0-P3")
    idempotency_key: str | None = Field(default=None, description="幂等键，重复提交只建一次")


class DraftReportArgs(BaseModel):
    title: str
    sections: list[str] = Field(default_factory=list)


def search_code(args: dict[str, object]) -> dict[str, object]:
    query = str(args.get("query", ""))
    top_k = int(args.get("top_k", 5))  # type: ignore[arg-type]
    pattern = re.compile(re.escape(query), re.IGNORECASE)
    hits: list[dict[str, object]] = []
    for path in sorted((ROOT / "src").rglob("*.py")):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if pattern.search(line):
                hits.append(
                    {
                        "file": str(path.relative_to(ROOT)).replace("\\", "/"),
                        "line": number,
                        "snippet": line.strip()[:160],
                    }
                )
                break
        if len(hits) >= top_k:
            break
    return {"query": query, "hits": hits, "count": len(hits)}


def query_metrics(args: dict[str, object]) -> dict[str, object]:
    service = str(args.get("service", "order-service"))
    window = str(args.get("window", "1h"))
    path = DATA_DIR / "metrics.json"
    if not path.exists():
        return {"service": service, "window": window, "series": [], "note": "无样例数据"}
    data = json.loads(path.read_text(encoding="utf-8"))
    services = data.get("services", {})
    return {
        "service": service,
        "window": window,
        "series": services.get(service, services.get("default", [])),
    }


def create_ticket(args: dict[str, object]) -> dict[str, object]:
    title = str(args.get("title", ""))
    key = str(args.get("idempotency_key") or title)
    digest = f"{abs(hash(key)) % 90000 + 10000}"
    return {
        "ticket_id": f"OPS-{digest}",
        "title": title,
        "severity": str(args.get("severity", "P2")),
        "status": "created",
        "idempotency_key": key,
    }


def draft_report(args: dict[str, object]) -> dict[str, object]:
    sections = args.get("sections") or ["现状", "根因", "处理方案", "后续改进"]
    lines = [f"# {args.get('title', '处理报告')}", ""]
    for section in sections:  # type: ignore[union-attr]
        lines.append(f"## {section}")
        lines.append("（待补充）")
        lines.append("")
    return {"markdown": "\n".join(lines), "sections_count": len(sections)}  # type: ignore[arg-type]
