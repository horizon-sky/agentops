"""工具执行：并行只读调用，写类工具先 interrupt 挂起等待人工确认（HITL）。"""

from __future__ import annotations

import asyncio
import re
from typing import Any

from langgraph.types import interrupt

from src.agent.context import bind
from src.agent.context import get as ctx_get
from src.agent.emit import event_of, get_emit
from src.agent.state import AgentState
from src.agent.tracing import Timer, TraceRecorder

# 意图 → 只读工具映射；写类工具只在明确建单意图时出现
_INTENT_TOOLS: dict[str, list[str]] = {
    "incident": ["query_metrics", "search_code"],
    "code": ["search_code"],
    "knowledge": [],
    "ticket": ["search_code", "create_ticket"],
    "general": ["search_code"],
}


def _planned_calls(state: AgentState) -> list[dict[str, Any]]:
    intent = state.get("intent", "general")
    names = _INTENT_TOOLS.get(intent, _INTENT_TOOLS["general"])
    query = state.get("query", "")
    severity = re.search(r"\bP[0-3]\b", query, re.IGNORECASE)
    return [
        {
            "name": name,
            "args": (
                {
                    "title": query[:300],
                    "detail": query,
                    "severity": severity.group().upper() if severity else "P2",
                }
                if name == "create_ticket"
                else {"query": query}
            ),
        }
        for name in names
    ]


async def tools(state: AgentState, config: Any | None = None) -> dict[str, Any]:
    settings = ctx_get("settings")
    emit = get_emit(config)
    timer = Timer()
    run_id = state.get("run_id", "")

    calls = state.get("pending_calls") or _planned_calls(state)
    results: list[dict[str, Any]] = []

    try:
        from src.tools.registry import get_registry
    except Exception:  # noqa: BLE001 - M3 未就绪时无工具可执行
        await emit(
            event_of(
                type="tool_result",
                run_id=run_id,
                stage="tools",
                payload={"name": "-", "ok": False, "error": "工具层未就绪"},
            )
        )
        return {"tool_results": results}

    registry = get_registry(settings)

    # 写类工具：先发审批事件，再挂起；用户确认后本节点从检查点重新执行
    approved_calls: list[dict[str, Any]] = []
    for index, pending in enumerate(calls):
        if not registry.is_high_risk(pending["name"]):
            approved_calls.append(pending)
            continue
        await emit(
            event_of(
                type="hitl_request",
                run_id=run_id,
                stage="tools",
                payload={
                    "tool": pending["name"],
                    "args": pending.get("args", {}),
                    "reason": f"写操作需人工确认（{pending['name']}）",
                },
            )
        )
        approved = interrupt(
            {"type": "hitl", "tool": pending["name"], "args": pending.get("args", {})}
        )
        if not isinstance(approved, dict) or not approved.get("ok"):
            denied = {
                "name": pending["name"],
                "args": pending.get("args", {}),
                "ok": False,
                "error": "用户拒绝或未确认",
                "risk": "high",
            }
            results.append(denied)
            await emit(event_of(type="tool_result", run_id=run_id, stage="tools", payload=denied))
        else:
            args = dict(approved.get("args") or pending.get("args", {}))
            if pending["name"] == "create_ticket":
                # Internal key cannot be changed in the approval form.
                args["idempotency_key"] = (
                    pending.get("args", {}).get("idempotency_key") or f"{run_id}:write:{index}"
                )
            approved_calls.append({**pending, "args": args})

    async def run_one(call: dict[str, Any]) -> dict[str, Any]:
        bind(write_approved=registry.is_high_risk(call["name"]))
        result = await registry.call(call["name"], call.get("args", {}))
        payload = result.model_dump()
        await emit(
            event_of(
                type="tool_result",
                run_id=run_id,
                stage="tools",
                payload=payload,
                ms=result.ms,
            )
        )
        return payload

    # 只读工具并行执行，压缩整体延迟
    results.extend(await asyncio.gather(*(run_one(call) for call in approved_calls)))

    await TraceRecorder(settings, run_id).record(
        run_id=run_id,
        stage="tools",
        name="tool_batch",
        inputs={"calls": [call["name"] for call in calls]},
        outputs={"results": [item["name"] for item in results]},
        ms=timer.ms,
    )
    return {"tool_results": results, "pending_calls": []}
