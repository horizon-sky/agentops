"""任务规划：产出可展示的执行步骤。"""

from __future__ import annotations

from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from src.agent.context import get as ctx_get
from src.agent.emit import event_of, get_emit
from src.agent.model import LLMProvider
from src.agent.prompts import SYSTEM_PLAN
from src.agent.state import AgentState
from src.agent.tracing import Timer, TraceRecorder


class PlanOut(BaseModel):
    steps: list[str] = Field(default_factory=list)


FALLBACK_STEPS = ["解析问题", "检索知识库", "调用工具取证", "生成处理方案"]


async def plan(state: AgentState, config: Any | None = None) -> dict[str, Any]:
    settings = ctx_get("settings")
    llm: LLMProvider | None = ctx_get("llm")
    emit = get_emit(config)
    timer = Timer()

    steps: list[str] = list(FALLBACK_STEPS)
    if llm is not None:
        result = await llm.acomplete(
            [SystemMessage(content=SYSTEM_PLAN), HumanMessage(content=state["query"])],
            tier="cheap",
            response_model=PlanOut,
        )
        parsed: PlanOut | None = result.parsed
        if parsed is not None and parsed.steps:
            steps = parsed.steps[:5]

    await TraceRecorder(settings, state.get("run_id")).record(
        run_id=state.get("run_id", ""),
        stage="plan",
        name="plan",
        inputs={"query": state["query"][:500]},
        outputs={"steps": steps},
        ms=timer.ms,
    )
    await emit(
        event_of(
            type="plan",
            run_id=state.get("run_id", ""),
            stage="plan",
            payload={"steps": steps},
            ms=timer.ms,
        )
    )
    return {"plan": steps}
