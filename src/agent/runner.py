"""Agent 执行器：EchoRunner（链路跑通）与 GraphRunner（LangGraph 编排）。"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any, Protocol, runtime_checkable

from langchain_core.messages import HumanMessage
from langgraph.types import Command

from apps.api.src.schemas.events import AgentEvent, make_event
from src.agent.context import bind
from src.agent.graph import build_graph
from src.agent.model import build_llm
from src.agent.planning import ExecutionPlan, PlanStep
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
        retrieval = {"mode": "echo", "status": "not_executed", "reason": "echo_mode"}
        await emit(
            make_event(
                type="plan",
                run_id=run_id,
                stage="plan",
                payload={
                    "plan": ExecutionPlan(
                        steps=[
                            PlanStep(id="answer", kind="answer", goal="演示事件流", status="done")
                        ]
                    ).model_dump()
                },
            )
        )
        await emit(
            make_event(
                type="retrieve",
                run_id=run_id,
                stage="retrieve",
                payload={
                    "hits": 0,
                    "note": "echo 模式未执行检索",
                    "citations": [],
                    "retrieval": retrieval,
                },
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
                payload={"answer": "".join(chunks), "citations": [], "retrieval": retrieval},
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
        return {
            "configurable": {
                "thread_id": run_id,
            },
            "recursion_limit": 64,
        }

    async def awaiting_approval(self, run_id: str) -> bool:
        graph, _persisted = await build_graph(self.settings, self.llm)
        checkpoint = await graph.aget_state({"configurable": {"thread_id": run_id}})
        return any(task.interrupts for task in checkpoint.tasks)

    async def approval(self, run_id: str) -> dict[str, Any]:
        graph, _ = await build_graph(self.settings, self.llm)
        checkpoint = await graph.aget_state({"configurable": {"thread_id": run_id}})
        return next((i.value for task in checkpoint.tasks for i in task.interrupts), {})

    async def _invoke(self, graph, value, config) -> None:
        checkpoint = await graph.aget_state(config)
        used = checkpoint.values.get("execution_ms", 0) if checkpoint.values else 0
        remaining = max(0.01, self.settings.agent_max_execution_s - used / 1000)
        deadline = asyncio.timeout(remaining)
        try:
            async with deadline:
                await graph.ainvoke(value, config)
        except TimeoutError:
            if not deadline.expired():
                raise
            checkpoint = await graph.aget_state(config)
            current = checkpoint.values or value
            plan = current.get("plan") or ExecutionPlan(
                steps=[PlanStep(id="answer", kind="answer", goal="说明执行时间上限")]
            ).model_dump()
            for step in plan["steps"]:
                if step["kind"] != "answer" and step["status"] in {"pending", "running"}:
                    step["status"] = "skipped"
            await graph.aupdate_state(
                config,
                {
                    **current,
                    "plan": plan,
                    "sufficient": False,
                    "stop_reason": "execution_budget",
                    "execution_ms": int(self.settings.agent_max_execution_s * 1000),
                    "review": {
                        "sufficient": False,
                        "reason": "达到累计执行时间上限，未完成的证据收集已停止",
                        "missing_evidence": ["时间预算内未完成的证据"],
                        "next_action": "answer",
                        "stop_reason": "execution_budget",
                    },
                },
                as_node="review",
            )
            # Finalize deterministically; do not spend another model call after the budget.
            await graph.ainvoke(None, config)

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
            "plan": {},
            "flags": self.settings.agent_flags(),
            "execution_ms": 0,
            "read_calls": 0,
            "citations": [],
            "retrieval": {"mode": "graph", "status": "not_executed", "reason": "not_started"},
            "tool_results": [],
            "retry": 0,
        }
        if pending_calls:
            state["pending_calls"] = pending_calls
        try:
            await self._invoke(graph, state, self._config(run_id, emit, user_id))
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
        requests = [i.value for task in checkpoint.tasks for i in task.interrupts]
        if not requests:
            raise ValueError("No pending approval")
        if payload.get("approval_id") != requests[0].get("approval_id"):
            raise ValueError("approval_id mismatch")
        bind(resuming_approval=requests[0].get("approval_id"))
        try:
            await self._invoke(graph, Command(resume=payload), config)
        except Exception as exc:  # noqa: BLE001
            if type(exc).__name__ == "GraphInterrupt":
                return
            raise
        finally:
            bind(resuming_approval=None)


def get_runner(settings: Settings | None = None) -> Runner:
    settings = settings or get_settings()
    if settings.agent_mode == "graph":
        return GraphRunner(settings)
    return EchoRunner(settings)
