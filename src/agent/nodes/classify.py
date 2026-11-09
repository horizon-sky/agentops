"""意图分类：低置信度直接结束并提示补充信息，避免无意义执行。"""

from __future__ import annotations

import re
from typing import Any, Literal

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
    requested_tools: list[
        Literal["query_metrics", "search_code", "create_ticket", "draft_report"]
    ] = Field(default_factory=list)


RULES: list[tuple[tuple[str, ...], str]] = [
    (("忽略以上", "忽略前面的", "忽略之前"), "injection"),
    (("建单", "工单", "创建单"), "ticket"),
    (("报警", "5xx", "超时", "延迟", "失败率", "故障", "排查", "连接池"), "incident"),
    (("代码", "文件", "函数", "定位", "哪个类", "实现", "位置", "查询语句"), "code"),
    (("规范", "流程", "知识库", "文档", "准入", "优先级"), "knowledge"),
]

INJECTION_PHRASES = ("忽略审批规则", "绕过审批", "绕过系统限制", "忽略系统提示")
TICKET_DENIAL_PHRASES = ("拒绝创建工单", "拒绝建单", "拒绝创建单")
TICKET_CONFIRMATION_PATTERN = r"^确认创建(?:[，,。!！\s].*)?$"

CLARIFICATION_MESSAGE = "当前信息不足，暂未执行后续步骤。请补充具体服务、时间范围和现象。"


def is_ticket_denial(query: str) -> bool:
    """识别明确拒绝创建，不把“先不要创建，等确认”误判为拒绝。"""
    normalized = re.sub(r"[\s，,。.!！、；;：:]+", "", query)
    if any(phrase in normalized for phrase in TICKET_DENIAL_PHRASES):
        return True
    return bool(
        re.search(
            r"(?:拒绝|否决|取消)(?:创建|新建|建立|提交|建)(?:这个|该|此)?(?:工单|工单草稿|单)?",
            normalized,
        )
    )


def rule_intent(query: str) -> str:
    """模型不可用或无法给出结构化结果时的确定性兜底，保证链路仍可运行。"""
    if any(phrase in query for phrase in INJECTION_PHRASES):
        return "injection"
    for keywords, intent in RULES:
        if any(keyword in query for keyword in keywords):
            return intent
    return "general"


async def classify(state: AgentState, config: Any | None = None) -> dict[str, Any]:
    settings = ctx_get("settings")
    llm: LLMProvider | None = ctx_get("llm")
    emit = get_emit(config)
    timer = Timer()

    query = state["query"]
    intent, confident, reason = "general", True, ""
    requested_tools: list[str] = []
    write_denied = is_ticket_denial(query)
    ticket_confirmation = bool(re.fullmatch(TICKET_CONFIRMATION_PATTERN, query.strip()))
    ticket_draft = None
    ticket_decision: dict[str, Any] = {}
    ticket_confirmation_error = False
    if ticket_confirmation:
        from src.agent.nodes.tools import _ticket_draft_from_history

        ticket_draft = _ticket_draft_from_history(state)
        if ticket_draft is None:
            ticket_confirmation_error = True
            intent, reason = "ticket", "当前会话没有可匹配的待确认工单草稿"
        else:
            intent = "ticket"
            requested_tools = ["create_ticket"]
            reason = "用户已通过后续消息明确确认当前待确认草稿"
    elif any(phrase in query for phrase in INJECTION_PHRASES):
        intent, reason = "injection", "检测到明确的审批或系统限制绕过请求"
    elif write_denied:
        from src.agent.nodes.tools import _ticket_draft_from_history

        prior_draft = _ticket_draft_from_history(state)
        ticket_decision = {
            "status": "denied",
            "tool": "create_ticket",
            "draft_run_id": prior_draft.get("run_id") if prior_draft else None,
            "draft_fingerprint": prior_draft.get("fingerprint") if prior_draft else None,
        }
        intent, reason = "ticket", "用户明确拒绝创建工单"
    elif llm is not None:
        try:
            result = await llm.acomplete(
                [SystemMessage(content=SYSTEM_CLASSIFY), HumanMessage(content=query)],
                tier="cheap",
                response_model=IntentOut,
            )
            parsed: IntentOut | None = result.parsed
        except Exception:
            parsed = None
        if parsed is not None:
            intent, confident, reason = parsed.intent, parsed.confident, parsed.reason
            requested_tools = parsed.requested_tools if confident else []
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
                payload={
                    "answer": CLARIFICATION_MESSAGE,
                    "citations": [],
                    "retrieval": {
                        "mode": "graph",
                        "status": "not_executed",
                        "reason": "clarification",
                    },
                },
                ms=timer.ms,
            )
        )
    return {
        "intent": intent,
        "requested_tools": requested_tools if intent != "injection" else [],
        "confident": confident,
        "write_denied": write_denied,
        "ticket_confirmation": ticket_confirmation and ticket_draft is not None,
        "ticket_draft": ticket_draft or {},
        "ticket_confirmation_error": ticket_confirmation_error,
        "ticket_decision": ticket_decision,
        **({"answer": CLARIFICATION_MESSAGE} if not confident else {}),
        "execution_ms": state.get("execution_ms", 0) + timer.ms,
    }
