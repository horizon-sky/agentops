"""生成：流式输出 token，并在结束时给出引用与工具摘要。"""

from __future__ import annotations

from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from src.agent.context import get as ctx_get
from src.agent.emit import event_of, get_emit
from src.agent.model import LLMProvider
from src.agent.prompts import ANSWER_TEMPLATE, SYSTEM_ANSWER
from src.agent.state import AgentState
from src.agent.tracing import Timer, TraceRecorder


def _build_context(state: AgentState) -> str:
    lines = []
    for index, citation in enumerate(state.get("citations", []), start=1):
        lines.append(
            f"[{citation.get('citation_id') or citation.get('chunk_id', index)}] "
            f"{citation.get('title', '')}: "
            f"{citation.get('snippet', '')}"
        )
    return "\n".join(lines) or "（无参考资料）"


def _build_tool_summary(state: AgentState) -> str:
    parts = []
    for item in state.get("tool_results", []):
        status = "成功" if item.get("ok") else f"失败({item.get('error')})"
        parts.append(f"- {item.get('name')}: {status} {str(item.get('output'))[:200]}")
    return "\n".join(parts) or "（未调用工具）"


async def answer(state: AgentState, config: Any | None = None) -> dict[str, Any]:
    settings = ctx_get("settings")
    llm: LLMProvider | None = ctx_get("llm")
    emit = get_emit(config)
    timer = Timer()
    run_id = state.get("run_id", "")
    review = state.get("review", {})
    plan = state.get("plan", {})
    for step in plan.get("steps", []):
        if step["kind"] == "answer":
            step["status"] = "done"
        elif step["status"] in {"pending", "running"}:
            step["status"] = "skipped"

    if state.get("intent") == "injection":
        # 确定性兜底策略：命中注入意图时拒绝执行，不调用模型
        text = "抱歉，该请求要求绕过系统限制，无法执行。请描述具体的技术问题，我会按流程处理。"
        await emit(event_of(type="token", run_id=run_id, stage="generate", payload={"delta": text}))
    elif review.get("next_action") == "clarify":
        text = "请补充：" + "；".join(
            review.get("missing_evidence") or [review.get("reason") or "具体问题信息"]
        )
        await emit(event_of(type="token", run_id=run_id, stage="generate", payload={"delta": text}))
    elif state.get("stop_reason") == "execution_budget":
        text = (
            f"已保留 {len(state.get('citations', []))} 条引用及 "
            f"{len(state.get('tool_results', []))} 项工具结果。"
            "未完成操作已停止；已提交的业务操作不会撤销。"
        )
        await emit(event_of(type="token", run_id=run_id, stage="generate", payload={"delta": text}))
    elif llm is None:
        text = f"[无模型] 已收集 {len(state.get('citations', []))} 条参考资料。"
        await emit(event_of(type="token", run_id=run_id, stage="generate", payload={"delta": text}))
    else:
        prompt = ANSWER_TEMPLATE.format(
            query=state["query"],
            context=_build_context(state),
            tool_results=_build_tool_summary(state),
        ) + ("\n证据审查：" + str(review) + "。证据不足时明确说明限制，不得宣称已经确认。")
        deltas: list[str] = []
        async for delta in llm.astream(
            [SystemMessage(content=SYSTEM_ANSWER), HumanMessage(content=prompt)],
            tier="strong",
        ):
            deltas.append(delta)
            await emit(
                event_of(type="token", run_id=run_id, stage="generate", payload={"delta": delta})
            )
        text = "".join(deltas)
    if review.get("sufficient") is False and review.get("next_action") != "clarify":
        gap = "；".join(
            review.get("missing_evidence") or [review.get("reason") or "缺少可验证证据"]
        )
        text = f"证据不足：{gap}。\n\n{text}"

    await TraceRecorder(settings, run_id).record(
        run_id=run_id,
        stage="generate",
        name="answer",
        inputs={"query": state["query"][:500]},
        outputs={"length": len(text)},
        ms=timer.ms,
    )
    await emit(
        event_of(
            type="done",
            run_id=run_id,
            stage="generate",
            payload={
                "answer": text,
                "citations": state.get("citations", []),
                "retrieval": state.get("retrieval", {}),
                "tools": state.get("tool_results", []),
                "plan": plan,
                "review": review,
            },
            ms=timer.ms,
        )
    )
    return {"answer": text, "plan": plan, "execution_ms": state.get("execution_ms", 0) + timer.ms}
