"""Agent 执行器：EchoRunner（链路跑通）与 GraphRunner（LangGraph 编排）。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Protocol, runtime_checkable

from langchain_core.messages import HumanMessage
from langgraph.types import Command

from apps.api.src.schemas.events import AgentEvent, make_event
from src.agent.context import bind
from src.agent.graph import build_graph
from src.agent.model import build_llm
from src.config import Settings, get_settings

Emit = Callable[[AgentEvent], Awaitable[None]]


@runtime_checkable
class Runner(Protocol):
    async def run(self, run_id: str, query: str, emit: Emit, *, user_id: str = "") -> None: ...


class EchoRunner:
    """无模型密钥时的链路跑通用执行器：产出计划 + 流式 token + done。"""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.llm = build_llm(settings)

    async def run(self, run_id: str, query: str, emit: Emit, *, user_id: str = "") -> None:
        await emit(
            make_event(
                type="plan",
                run_id=run_id,
                stage="plan",
                payload={"steps": ["解析问题", "检索知识库", "整理处理方案"]},
            )
        )
        await emit(
            make_event(
                type="retrieve",
                run_id=run_id,
                stage="retrieve",
                payload={"hits": 0, "note": "M4 接入混合检索前为空"},
                ms=0,
            )
        )

        chunks: list[str] = []
        async for delta in self.llm.astream([HumanMessage(content=query)]):
            chunks.append(delta)
            await emit(
                make_event(
                    type="token",
                    run_id=run_id,
                    stage="generate",
                    payload={"delta": delta},
                )
            )

        await emit(
            make_event(
                type="done",
                run_id=run_id,
                payload={"answer": "".join(chunks), "citations": []},
            )
        )


class GraphRunner:
    """LangGraph 执行器：节点内自行发送事件，HITL 挂起后等待 resume。"""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.llm = build_llm(settings)

    def _config(self, run_id: str, emit: Emit, user_id: str = "") -> dict[str, Any]:
        # 依赖通过 contextvars 注入节点，config 只保留 LangGraph 需要的 thread_id
        bind(emit=emit, settings=self.settings, llm=self.llm, run_id=run_id, user_id=user_id)
        return {"configurable": {"thread_id": run_id}}

    async def awaiting_approval(self, run_id: str) -> bool:
        graph, _persisted = await build_graph(self.settings, self.llm)
        checkpoint = await graph.aget_state({"configurable": {"thread_id": run_id}})
        return any(task.interrupts for task in checkpoint.tasks)

    async def run(
        self,
        run_id: str,
        query: str,
        emit: Emit,
        pending_calls: list[dict[str, Any]] | None = None,
        *,
        user_id: str = "",
    ) -> None:
        graph, _persisted = await build_graph(self.settings, self.llm)
        state: dict[str, Any] = {
            "run_id": run_id,
            "session_id": "",
            "user_id": user_id,
            "query": query,
            "plan": [],
            "citations": [],
            "tool_results": [],
            "retry": 0,
        }
        if pending_calls:
            state["pending_calls"] = pending_calls
        try:
            await graph.ainvoke(state, self._config(run_id, emit, user_id))
        except Exception as exc:  # noqa: BLE001
            # interrupt() 抛出 GraphInterrupt：任务处于等待人工确认状态，不视为失败
            if type(exc).__name__ == "GraphInterrupt":
                return
            raise

    async def resume(
        self, run_id: str, payload: dict[str, Any], emit: Emit, *, user_id: str = ""
    ) -> None:
        graph, _persisted = await build_graph(self.settings, self.llm)
        config = self._config(run_id, emit, user_id)
        checkpoint = await graph.aget_state(config)
        if checkpoint.values.get("user_id", "") != user_id:
            raise PermissionError("checkpoint owner mismatch")
        try:
            await graph.ainvoke(Command(resume=payload), config)
        except Exception as exc:  # noqa: BLE001
            if type(exc).__name__ == "GraphInterrupt":
                return
            raise


def get_runner(settings: Settings | None = None) -> Runner:
    settings = settings or get_settings()
    if settings.agent_mode == "graph":
        return GraphRunner(settings)
    return EchoRunner(settings)
