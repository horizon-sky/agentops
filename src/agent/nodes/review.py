"""自审：判断证据是否充分，不足则回到 plan 重新规划（最多 2 次）。"""

from __future__ import annotations

from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from src.agent.context import get as ctx_get
from src.agent.emit import event_of, get_emit
from src.agent.model import LLMProvider
from src.agent.prompts import SYSTEM_REVIEW
from src.agent.state import AgentState
from src.agent.tracing import Timer, TraceRecorder

MAX_RETRY = 2


class ReviewOut(BaseModel):
    sufficient: bool = Field(default=True)
    reason: str = Field(default="")


async def review(state: AgentState, config: Any | None = None) -> dict[str, Any]:
    settings = ctx_get("settings")
    llm: LLMProvider | None = ctx_get("llm")
    emit = get_emit(config)
    timer = Timer()

    sufficient = True
    reason = ""
    if llm is not None:
        evidence = {
            "citations": len(state.get("citations", [])),
            "tools": [item.get("name") for item in state.get("tool_results", [])],
            "tool_ok": all(item.get("ok") for item in state.get("tool_results", [])),
        }
        result = await llm.acomplete(
            [
                SystemMessage(content=SYSTEM_REVIEW),
                HumanMessage(content=f"问题：{state['query']}\n证据：{evidence}"),
            ],
            tier="cheap",
            response_model=ReviewOut,
        )
        parsed: ReviewOut | None = result.parsed
        if parsed is not None:
            sufficient, reason = parsed.sufficient, parsed.reason

    retry = state.get("retry", 0)
    if not sufficient:
        retry += 1
        if retry > MAX_RETRY:  # 超过上限不再空转，直接进入生成并说明不确定性
            sufficient, reason = True, f"重试已达上限（{MAX_RETRY}），按现有证据作答"

    await TraceRecorder(settings, state.get("run_id")).record(
        run_id=state.get("run_id", ""),
        stage="tools",
        name="review",
        inputs={"retry": retry},
        outputs={"sufficient": sufficient, "reason": reason},
        ms=timer.ms,
    )
    await emit(
        event_of(
            type="plan",
            run_id=state.get("run_id", ""),
            stage="plan",
            payload={"review": {"sufficient": sufficient, "reason": reason, "retry": retry}},
            ms=timer.ms,
        )
    )
    return {"sufficient": sufficient, "retry": retry}
