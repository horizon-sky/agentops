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
    ticket_draft = (
        state.get("ticket_draft") or _ticket_draft_from_history(state) if confirmation else None
    )
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
    if intent == "ticket" and not confirmation and "报告" not in query:
        # 工单草稿由 answer 节点生成；draft_report 是独立的高风险报告工具，
        # 不应因“草稿”二字被模型误选进两轮建单流程。
        tools = [name for name in tools if name != "draft_report"]
    if intent == "ticket" and not confirmation:
        tools = [name for name in tools if name != "create_ticket"]
    tools = list(dict.fromkeys([*_INTENT_TOOLS.get(intent, []), *tools]))

    def tool_args(name: str) -> dict[str, Any]:
        if name == "create_ticket":
            return {
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
                )
            }
        if name == "query_metrics":
            return {"service": "order-service", "window": "1h"}
        if name == "draft_report":
            return {
                "title": query[:300],
                "sections": ["现状", "根因", "处理方案", "后续改进"],
            }
        return {"query": query}

    calls = [
        {"name": name, "args": tool_args(name)}
        for name in tools
    ]
    if confirmation and ticket_draft is None:
        return [call for call in calls if call["name"] != "create_ticket"]
    return calls


def _ticket_draft_from_history(state: AgentState) -> dict[str, Any] | None:
    from src.agent.nodes.classify import TICKET_DENIAL_PHRASES

    history = state.get("conversation_history", [])
    for turn in reversed(history):
        if any(phrase in str(turn.get("query", "")) for phrase in TICKET_DENIAL_PHRASES):
            return None
        # A successful write consumes all earlier drafts, regardless of answer wording.
        if _has_successful_ticket_write(turn):
            return None
        if turn.get("status") != "completed":
            continue
        stored_draft = turn.get("ticket_draft")
        if stored_draft:
            if not _valid_stored_ticket_draft(stored_draft, turn.get("run_id", "")):
                return None
            return dict(stored_draft)
        # Legacy rendered text is deliberately non-authoritative. If it looks like
        # a draft, stop here instead of approving an older draft from this session.
        answer = str(turn.get("answer", ""))
        if "草稿" in answer or "标题：" in answer or "**标题" in answer:
            return None
    return None


def _valid_stored_ticket_draft(draft: Any, run_id: str) -> bool:
    if not isinstance(draft, dict) or draft.get("run_id") != str(run_id):
        return False
    title = str(draft.get("title", "")).strip()
    detail = str(draft.get("detail", "")).strip()
    severity = str(draft.get("severity", "")).upper().strip()
    fingerprint = str(draft.get("fingerprint", ""))
    return bool(title and detail and severity in {"P0", "P1", "P2", "P3"}) and (
        fingerprint == _ticket_draft_fingerprint(title, severity, detail)
    )


def _ticket_draft_fingerprint(title: str, severity: str, detail: str) -> str:
    return hashlib.sha256(f"{title}\n{severity}\n{detail}".encode()).hexdigest()


def _validate_ticket_draft_payload(
    draft: dict[str, Any] | None, args: dict[str, Any]
) -> None:
    if draft is None:
        raise ValueError("ticket draft is missing; refusing to create ticket")
    if not draft.get("run_id"):
        raise ValueError("ticket draft source is missing; refusing to create ticket")
    title = str(args.get("title", "")).strip()
    detail = str(args.get("detail", "")).strip()
    severity = str(args.get("severity", "")).strip().upper()
    if not title or not detail or severity not in {"P0", "P1", "P2", "P3"}:
        raise ValueError("ticket draft payload is incomplete; refusing to create ticket")
    fingerprint = _ticket_draft_fingerprint(title, severity, detail)
    if (
        draft.get("fingerprint") != fingerprint
        or draft.get("title") != title
        or draft.get("detail") != detail
        or str(draft.get("severity", "")).upper() != severity
    ):
        raise ValueError("ticket payload does not match approved draft; refusing to create ticket")


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
                _validate_ticket_draft_payload(state.get("ticket_draft"), args)
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
                            "args": dict(args),
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
