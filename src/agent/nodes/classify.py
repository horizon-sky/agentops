"""意图分类：低置信度直接结束并提示补充信息，避免无意义执行。"""

from __future__ import annotations

from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from src.agent.context import get as ctx_get
from src.agent.emit import event_of, get_emit
from src.agent.model import LLMProvider
from src.agent.prompts import SYSTEM_CLASSIFY
from src.agent.state import AgentState
from src.agent.tracing import Timer, TraceRecorder


class IntentOut(BaseModel):
    intent: str = Field(default="general")
    confident: bool = Field(default=True)
    reason: str = Field(default="")


RULES: list[tuple[tuple[str, ...], str]] = [
    (("忽略以上", "忽略前面的", "忽略之前", "系统提示", "指令"), "injection"),
    (("建单", "工单", "创建单"), "ticket"),
    (("报警", "5xx", "超时", "延迟", "失败率", "故障", "排查", "连接池"), "incident"),
    (("代码", "文件", "函数", "定位", "哪个类", "实现", "位置", "查询语句"), "code"),
    (("规范", "流程", "知识库", "文档", "准入", "优先级"), "knowledge"),
]

CLARIFICATION_MESSAGE = "当前信息不足，暂未执行后续步骤。请补充具体服务、时间范围和现象。"


def rule_intent(query: str) -> str:
    """模型不可用或无法给出结构化结果时的确定性兜底，保证链路仍可运行。"""
    for keywords, intent in RULES:
        if any(keyword in query for keyword in keywords):
            return intent
    return "general"


async def classify(state: AgentState, config: Any | None = None) -> dict[str, Any]:
    settings = ctx_get("settings")
    llm: LLMProvider | None = ctx_get("llm")
    emit = get_emit(config)
    timer = Timer()

    intent, confident, reason = "general", True, ""
    if llm is not None:
        result = await llm.acomplete(
            [SystemMessage(content=SYSTEM_CLASSIFY), HumanMessage(content=state["query"])],
            tier="cheap",
            response_model=IntentOut,
        )
        parsed: IntentOut | None = result.parsed
        if parsed is not None:
            intent, confident, reason = parsed.intent, parsed.confident, parsed.reason
        else:
            intent, reason = rule_intent(state["query"]), "模型未返回结构化结果，使用规则兜底"

    recorder = TraceRecorder(settings, state.get("run_id"))
    await recorder.record(
        run_id=state.get("run_id", ""),
        stage="plan",
        name="classify",
        inputs={"query": state["query"][:500]},
        outputs={"intent": intent, "confident": confident},
        ms=timer.ms,
    )

    await emit(
        event_of(
            type="plan",
            run_id=state.get("run_id", ""),
            stage="plan",
            payload={"intent": intent, "confident": confident, "reason": reason},
            ms=timer.ms,
        )
    )
    if not confident:
        await emit(
            event_of(
                type="done",
                run_id=state.get("run_id", ""),
                stage="generate",
                payload={"answer": CLARIFICATION_MESSAGE, "citations": []},
                ms=timer.ms,
            )
        )
    return {"intent": intent, "confident": confident}
