"""LangGraph 状态图装配。

链路：classify → plan → dispatch → 按需 retrieve/tools → review → answer
- classify 判定信息不足则直接结束（不浪费工具调用）
- review 根据缺口补充只读步骤后回到 dispatch，最多补证 2 次
- tools 节点内的写类工具通过 interrupt 挂起，等待人工确认后从检查点恢复
"""

from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack

from langgraph.graph import END, StateGraph

from src.agent.checkpointer import build_checkpointer
from src.agent.model import LLMProvider, build_llm
from src.agent.nodes import answer, classify, plan, retrieve, review, tools
from src.agent.nodes.dispatch import dispatch, route
from src.agent.state import AgentState
from src.config import Settings

_graph_cache: dict[str, tuple[object, bool, AsyncExitStack]] = {}
_lock = asyncio.Lock()


def _route_after_classify(state: AgentState) -> str:
    return "plan" if state.get("confident", True) else END


def _route_after_review(state: AgentState) -> str:
    if state.get("review", {}).get("next_action") in {"retrieve", "tools"}:
        return "dispatch"
    return "answer"


async def build_graph(settings: Settings, llm: LLMProvider | None = None):
    """编译状态图；返回 (compiled_graph, 检查点是否持久化)。"""
    async with _lock:
        # Resume reconstructs the settings snapshot; equivalent configs must share checkpoints.
        cache_key = settings.model_dump_json()
        cached = _graph_cache.get(cache_key)
        if cached is not None:
            return cached[0], cached[1]

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
        workflow.add_node("dispatch", dispatch)
        workflow.add_node("retrieve", retrieve)
        workflow.add_node("tools", tools)
        workflow.add_node("review", review)
        workflow.add_node("answer", answer)

        workflow.set_entry_point("classify")
        workflow.add_conditional_edges(
            "classify", _route_after_classify, {"plan": "plan", END: END}
        )
        workflow.add_edge("plan", "dispatch")
        workflow.add_conditional_edges(
            "dispatch", route, {"retrieve": "retrieve", "tools": "tools", "review": "review"}
        )
        workflow.add_edge("retrieve", "dispatch")
        workflow.add_edge("tools", "dispatch")
        workflow.add_conditional_edges(
            "review", _route_after_review, {"dispatch": "dispatch", "answer": "answer"}
        )
        workflow.add_edge("answer", END)

        compiled = workflow.compile(checkpointer=checkpointer)
        _graph_cache[cache_key] = (compiled, persisted, stack)
        return compiled, persisted


async def close_graphs() -> None:
    async with _lock:
        graphs = list(_graph_cache.values())
        _graph_cache.clear()
        for _, _, stack in graphs:
            await stack.aclose()
