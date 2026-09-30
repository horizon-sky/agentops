"""LangGraph 状态图装配。

链路：classify → plan → retrieve → tools → review → answer
- classify 判定信息不足则直接结束（不浪费工具调用）
- review 判定证据不足则回到 plan，最多重试 2 次
- tools 节点内的写类工具通过 interrupt 挂起，等待人工确认后从检查点恢复
"""

from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack

from langgraph.graph import END, StateGraph

from src.agent.checkpointer import build_checkpointer
from src.agent.model import LLMProvider, build_llm
from src.agent.nodes import answer, classify, plan, retrieve, review, tools
from src.agent.nodes.review import MAX_RETRY
from src.agent.state import AgentState
from src.config import Settings

_graph_cache: dict[int, tuple[Settings, object, bool, AsyncExitStack]] = {}
_lock = asyncio.Lock()


def _route_after_classify(state: AgentState) -> str:
    return "plan" if state.get("confident", True) else END


def _route_after_review(state: AgentState) -> str:
    if not state.get("sufficient", True) and state.get("retry", 0) <= MAX_RETRY:
        return "plan"
    return "answer"


async def build_graph(settings: Settings, llm: LLMProvider | None = None):
    """编译状态图；返回 (compiled_graph, 检查点是否持久化)。"""
    async with _lock:
        cached = _graph_cache.get(id(settings))
        if cached is not None and cached[0] is settings:
            return cached[1], cached[2]

        llm = llm or build_llm(settings)
        stack = AsyncExitStack()
        try:
            checkpointer, persisted = await build_checkpointer(settings, stack)
        except BaseException:
            await stack.aclose()
            raise

        workflow = StateGraph(AgentState)
        workflow.add_node("classify", classify)
        workflow.add_node("plan", plan)
        workflow.add_node("retrieve", retrieve)
        workflow.add_node("tools", tools)
        workflow.add_node("review", review)
        workflow.add_node("answer", answer)

        workflow.set_entry_point("classify")
        workflow.add_conditional_edges(
            "classify", _route_after_classify, {"plan": "plan", END: END}
        )
        workflow.add_edge("plan", "retrieve")
        workflow.add_edge("retrieve", "tools")
        workflow.add_edge("tools", "review")
        workflow.add_conditional_edges(
            "review", _route_after_review, {"plan": "plan", "answer": "answer"}
        )
        workflow.add_edge("answer", END)

        compiled = workflow.compile(checkpointer=checkpointer)
        _graph_cache[id(settings)] = (settings, compiled, persisted, stack)
        return compiled, persisted


async def close_graphs() -> None:
    async with _lock:
        graphs = list(_graph_cache.values())
        _graph_cache.clear()
        for _, _, _, stack in graphs:
            await stack.aclose()
