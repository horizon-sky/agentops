"""Select dependency-ready work; persist each batch before advancing."""

from __future__ import annotations

from typing import Any

from src.agent.context import get as ctx_get
from src.agent.emit import event_of, get_emit
from src.agent.state import AgentState
from src.tools.registry import get_registry

TERMINAL = {"done", "failed", "denied", "skipped"}


async def dispatch(state: AgentState, config: Any | None = None) -> dict[str, Any]:
    settings = ctx_get("settings")
    plan = state["plan"]
    steps = plan["steps"]
    completed = {s["id"] for s in steps if s["status"] in TERMINAL}
    ready = [s for s in steps if s["status"] == "pending" and set(s["depends_on"]) <= completed]
    if state.get("execution_ms", 0) >= settings.agent_max_execution_s * 1000:
        return {"active_step_ids": [], "stop_reason": "execution_budget"}
    if not ready:
        return {"active_step_ids": []}
    retrieval = [s for s in ready if s["kind"] == "retrieve"]
    tools = [s for s in ready if s["kind"] == "tool"]
    registry = get_registry(settings)
    reads = [s for s in tools if not registry.is_high_risk(s["tool"])]
    if retrieval:
        selected = retrieval[:1]
    elif reads:
        available = max(0, settings.agent_max_read_calls - state.get("read_calls", 0))
        selected = reads[:available]
        for step in reads[available:]:
            step["status"] = "skipped"
        if not selected:
            return {"plan": plan, "active_step_ids": [], "stop_reason": "read_call_budget"}
    elif tools:
        selected = tools[:1]
    else:
        selected = []
    for step in selected:
        step["status"] = "running"
    await get_emit(config)(
        event_of(type="plan", run_id=state["run_id"], stage="plan", payload={"plan": plan})
    )
    return {"plan": plan, "active_step_ids": [s["id"] for s in selected]}


def route(state: AgentState) -> str:
    ids = state.get("active_step_ids", [])
    if ids:
        selected = next(s for s in state["plan"]["steps"] if s["id"] in ids)
        return "retrieve" if selected["kind"] == "retrieve" else "tools"
    return "review"
