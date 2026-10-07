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

    if state.get("intent") == "injection":
        # 确定性兜底策略：命中注入意图时拒绝执行，不调用模型
        text = "抱歉，该请求要求绕过系统限制，无法执行。请描述具体的技术问题，我会按流程处理。"
        await emit(event_of(type="token", run_id=run_id, stage="generate", payload={"delta": text}))
    elif llm is None:
        text = f"[无模型] 已收集 {len(state.get('citations', []))} 条参考资料。"
        await emit(event_of(type="token", run_id=run_id, stage="generate", payload={"delta": text}))
    else:
        prompt = ANSWER_TEMPLATE.format(
            query=state["query"],
            context=_build_context(state),
            tool_results=_build_tool_summary(state),
        )
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
            },
            ms=timer.ms,
        )
    )
    return {"answer": text}
