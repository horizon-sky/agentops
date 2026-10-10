"""Evidence batches precede separately checkpointed, approved writes."""

from __future__ import annotations

import asyncio
import re
from typing import Any

from langgraph.types import interrupt

from src.agent.context import bind
from src.agent.context import get as ctx_get
from src.agent.emit import event_of, get_emit
from src.agent.state import AgentState
from src.agent.tracing import Timer

_INTENT_TOOLS = {
    "incident": ["query_metrics", "search_code"],
    "code": ["search_code"],
    "knowledge": [],
    "ticket": ["search_code", "create_ticket"],
    "general": ["search_code"],
}


def _planned_calls(state: AgentState) -> list[dict[str, Any]]:
    query = state.get("query", "")
    severity = re.search(r"(?<![A-Za-z0-9])P[0-3](?![A-Za-z0-9])", query, re.IGNORECASE)
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
                else {"service": "order-service", "window": "1h"}
                if name == "query_metrics"
                else {"query": query}
            ),
        }
        for name in _INTENT_TOOLS.get(state.get("intent", "general"), [])
    ]


async def tools(state: AgentState, config: Any | None = None) -> dict[str, Any]:
    from src.tools.registry import get_registry

    registry = get_registry(ctx_get("settings"))
    emit, timer = get_emit(config), Timer()
    run_id = state["run_id"]
    plan = state["plan"]
    selected = [s for s in plan["steps"] if s["id"] in state["active_step_ids"]]
    operations = dict(state.get("operations", {}))
    results = list(state.get("tool_results", []))
    available = max(0, ctx_get("settings").agent_max_read_calls - state.get("read_calls", 0))
    attempt_limits = {}
    # Reserve at least one attempt per parallel read; retries share the remaining budget.
    reads = [s for s in selected if not registry.is_high_risk(s["tool"])]
    for index, step in enumerate(reads):
        limit = min(registry.specs[step["tool"]].retries + 1, available - len(reads) + index + 1)
        attempt_limits[step["id"]] = max(0, limit)
        available -= max(0, limit)

    async def execute(step: dict[str, Any]) -> dict[str, Any]:
        step_id = step["id"]
        key = f"{run_id}:{step_id}"
        if key in operations:
            return operations[key]
        args = dict(step["args"])
        write = registry.is_high_risk(step["tool"])
        if write:
            approval_id = key
            request = {
                "approval_id": approval_id,
                "step_id": step_id,
                "tool": step["tool"],
                "args": args,
                "reason": "写操作需人工确认",
            }
            if ctx_get("resuming_approval") != approval_id:
                await emit(
                    event_of(type="hitl_request", run_id=run_id, stage="tools", payload=request)
                )
            approved = interrupt(request)
            if not isinstance(approved, dict) or not approved.get("ok"):
                payload = {
                    "name": step["tool"],
                    "step_id": step_id,
                    "args": args,
                    "ok": False,
                    "error": "用户拒绝或未确认",
                    "risk": "high",
                    "denied": True,
                }
                await emit(
                    event_of(type="tool_result", run_id=run_id, stage="tools", payload=payload)
                )
                return payload
            if approved.get("approval_id") != approval_id:
                raise ValueError("approval_id mismatch")
            args.update(approved.get("args") or {})
            if step["tool"] == "create_ticket":
                args["idempotency_key"] = key
        bind(write_approved=write)
        try:
            if write:
                result = await registry.call(step["tool"], args)
            else:
                result = await registry.call(
                    step["tool"], args, max_attempts=attempt_limits[step_id]
                )
        finally:
            bind(write_approved=False)
        payload = {**result.model_dump(), "step_id": step_id}
        await emit(
            event_of(
                type="tool_result", run_id=run_id, stage="tools", payload=payload, ms=result.ms
            )
        )
        return payload

    # interrupt must stay in the LangGraph task; only independent reads use gather.
    if any(registry.is_high_risk(s["tool"]) for s in selected):
        batch = [await execute(selected[0])]
    else:
        batch = await asyncio.gather(*(execute(s) for s in selected))
    for step, result in zip(selected, batch, strict=True):
        operations[f"{run_id}:{step['id']}"] = result
        step["status"] = "done" if result["ok"] else "denied" if result.get("denied") else "failed"
        results = [r for r in results if r.get("step_id") != step["id"]] + [result]
    return {
        "plan": plan,
        "operations": operations,
        "tool_results": results,
        "read_calls": state.get("read_calls", 0)
        + sum(
            result.get("attempts", 0)
            for step, result in zip(selected, batch, strict=True)
            if not registry.is_high_risk(step["tool"])
        ),
        "execution_ms": state.get("execution_ms", 0) + timer.ms,
    }
