"""Evidence batches precede separately checkpointed, approved writes."""

from __future__ import annotations

import asyncio
import hashlib
import re
from typing import Any

from langgraph.types import interrupt

from src.agent.context import bind
from src.agent.context import get as ctx_get
from src.agent.emit import event_of, get_emit
from src.agent.state import AgentState
from src.agent.tracing import Timer

_INTENT_TOOLS = {
    "incident": [],
    "code": ["search_code"],
    "knowledge": [],
    "ticket": [],
    "general": [],
}


def _planned_calls(state: AgentState) -> list[dict[str, Any]]:
    query = state.get("query", "")
    severity = re.search(r"(?<![A-Za-z0-9])P[0-3](?![A-Za-z0-9])", query, re.IGNORECASE)
    confirmation = state.get("ticket_confirmation", False)
    ticket_draft = _ticket_draft_from_history(state) if confirmation else None
    intent = state.get("intent")
    if confirmation and ticket_draft is not None:
        intent = "ticket"
    allowed = {
        "incident": {"query_metrics", "search_code"},
        "code": {"search_code"},
        "ticket": {"query_metrics", "search_code", "create_ticket", "draft_report"},
        "knowledge": set(),
        "general": set(),
    }.get(intent, set())
    tools = [name for name in dict.fromkeys(state.get("requested_tools", [])) if name in allowed]
    if confirmation:
        tools = [name for name in tools if name != "create_ticket"]
        if ticket_draft is not None:
            tools.append("create_ticket")
    if intent == "code" and "search_code" not in tools:
        tools.append("search_code")
    tools = list(dict.fromkeys([*_INTENT_TOOLS.get(intent, []), *tools]))
    calls = [
        {
            "name": name,
            "args": (
                {
                    **(
                        {
                            key: ticket_draft[key]
                            for key in ("title", "detail", "severity")
                        }
                        if confirmation and ticket_draft is not None
                        else {
                            "title": query[:300],
                            "detail": query,
                            "severity": severity.group().upper() if severity else "P2",
                        }
                    ),
                }
                if name == "create_ticket"
                else {"service": "order-service", "window": "1h"}
                if name == "query_metrics"
                else {"query": query}
            ),
        }
        for name in tools
    ]
    if confirmation and ticket_draft is None:
        return [call for call in calls if call["name"] != "create_ticket"]
    return calls


def _ticket_draft_from_history(state: AgentState) -> dict[str, Any] | None:
    history = state.get("conversation_history", [])
    for turn in reversed(history):
        if turn.get("status") != "completed" or _has_successful_ticket_write(turn):
            continue
        answer = turn.get("answer", "")
        title_match = re.search(r"(?m)^标题：\s*(.+?)\s*$", answer)
        priority_match = re.search(r"(?m)^优先级：\s*(P[0-3])(?:\b|（)", answer)
        detail_match = re.search(
            r"(?ms)^描述：\s*\n(.*?)(?=\n\s*(?:当前状态|本次未调用工具)\s*[：。\n]|\Z)",
            answer,
        )
        if not title_match or not priority_match or not detail_match:
            continue
        title = re.sub(r"\s*\[[0-9a-fA-F-]{36}\]\s*$", "", title_match.group(1)).strip()
        detail = detail_match.group(1).strip()
        if not title or not detail:
            continue
        severity = priority_match.group(1)
        canonical = f"{title}\n{severity}\n{detail}".encode()
        return {
            "title": title,
            "detail": detail,
            "severity": severity,
            "run_id": str(turn.get("run_id", "")),
            "fingerprint": hashlib.sha256(canonical).hexdigest(),
        }
    return None


def _has_successful_ticket_write(turn: dict[str, Any]) -> bool:
    if any(
        result.get("name") == "create_ticket" and result.get("ok")
        for result in turn.get("tool_results", [])
    ):
        return True
    if any(
        event.get("tool") == "create_ticket"
        and event.get("event") == "executed"
        and event.get("ok")
        for event in turn.get("approval_history", [])
    ):
        return True
    return any(
        step.get("tool") == "create_ticket" and step.get("status") == "done"
        for step in turn.get("plan", {}).get("steps", [])
    )


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
            if step["tool"] == "create_ticket" and state.get("ticket_confirmation"):
                await emit(
                    event_of(
                        type="approval",
                        run_id=run_id,
                        stage="tools",
                        payload={
                            "event": "confirmed",
                            "approval_id": approval_id,
                            "step_id": step_id,
                            "tool": step["tool"],
                            "args": args,
                            "actor_id": state.get("user_id"),
                            "confirmation_text": state.get("query", ""),
                            "draft_run_id": state.get("ticket_draft", {}).get("run_id"),
                            "draft_fingerprint": state.get("ticket_draft", {}).get("fingerprint"),
                            "source": "explicit_follow_up_message",
                        },
                    )
                )
                args["idempotency_key"] = key
                bind(write_approved=True)
                try:
                    result = await registry.call(step["tool"], args)
                finally:
                    bind(write_approved=False)
                payload = {**result.model_dump(), "step_id": step_id}
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
