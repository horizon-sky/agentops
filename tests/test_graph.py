"""M2 编排：图装配、离线兜底执行与 HITL 挂起。"""

from __future__ import annotations

from typing import Any

import pytest

from apps.api.src.schemas.events import AgentEvent
from src.agent.context import bind
from src.agent.graph import build_graph
from src.agent.model import ModelResult
from src.agent.runner import GraphRunner
from src.config import Settings


class LowConfidenceLLM:
    async def acomplete(self, messages, tier="strong", response_model=None):
        from src.agent.nodes.classify import IntentOut

        return ModelResult(parsed=IntentOut(intent="general", confident=False, reason="信息不足"))

    async def astream(self, messages, tier="strong"):
        if False:
            yield ""


class Collector:
    def __init__(self) -> None:
        self.events: list[AgentEvent] = []

    async def __call__(self, event: AgentEvent) -> None:
        self.events.append(event)

    @property
    def types(self) -> list[str]:
        return [event.type for event in self.events]

    def payload_of(self, event_type: str) -> dict[str, Any]:
        for event in self.events:
            if event.type == event_type:
                return event.payload or {}
        return {}


async def test_graph_compiles_with_memory_checkpoint() -> None:
    settings = Settings(_env_file=None)
    _graph, persisted = await build_graph(settings)
    assert persisted is False  # 无数据库时使用内存检查点


async def test_graph_run_emits_plan_and_done_offline() -> None:
    settings = Settings(_env_file=None)
    collector = Collector()
    runner = GraphRunner(settings)
    await runner.run("run-graph-1", "订单服务 5xx 怎么排查？", collector)

    assert "plan" in collector.types
    assert "retrieve" in collector.types
    assert "tool_result" in collector.types
    assert collector.types[-1] == "done"
    assert "answer" in collector.payload_of("done")


async def test_low_confidence_classification_terminates_sse_with_done() -> None:
    settings = Settings(_env_file=None)
    collector = Collector()
    runner = GraphRunner(settings)
    runner.llm = LowConfidenceLLM()

    await runner.run("run-low-confidence", "帮我处理一下", collector)

    assert collector.types == ["plan", "done"]
    assert "补充" in collector.payload_of("done")["answer"]


async def test_high_risk_tool_triggers_hitl_and_suspends() -> None:
    settings = Settings(_env_file=None)
    collector = Collector()
    runner = GraphRunner(settings)

    # 通过 pending_calls 直接指定写类工具，验证 interrupt 路径
    initial_state = {
        "run_id": "run-hitl-1",
        "query": "帮我建一个 P1 工单",
        "pending_calls": [
            {"name": "create_ticket", "args": {"title": "订单服务 5xx", "severity": "P1"}}
        ],
        "citations": [],
        "tool_results": [],
        "plan": [],
        "retry": 0,
    }
    graph, _persisted = await build_graph(settings, runner.llm)
    bind(emit=collector, settings=settings, llm=runner.llm, run_id="run-hitl-1")
    config = {"configurable": {"thread_id": "run-hitl-1"}}
    try:
        await graph.ainvoke(initial_state, config)
    except Exception as exc:  # noqa: BLE001
        assert type(exc).__name__ == "GraphInterrupt"

    assert "hitl_request" in collector.types
    assert collector.payload_of("hitl_request")["tool"] == "create_ticket"
    assert "done" not in collector.types  # 未确认前不应产出最终答案
    _ = initial_state


async def test_rejected_write_tool_is_never_executed(monkeypatch) -> None:
    from src.tools.registry import ToolRegistry

    calls: list[str] = []

    async def call(self, name: str, args: dict[str, Any]):
        calls.append(name)
        raise AssertionError("rejected tool must not execute")

    monkeypatch.setattr(ToolRegistry, "call", call)
    settings = Settings(_env_file=None)
    collector = Collector()
    runner = GraphRunner(settings)
    await runner.run(
        "run-hitl-reject",
        "帮我建一个 P1 工单",
        collector,
        pending_calls=[
            {"name": "create_ticket", "args": {"title": "订单服务 5xx", "severity": "P1"}}
        ],
    )
    assert "hitl_request" in collector.types

    await runner.resume("run-hitl-reject", {"ok": False}, collector)

    assert calls == []
    assert any(
        event.type == "tool_result" and event.payload.get("error") == "用户拒绝或未确认"
        for event in collector.events
    )


async def test_only_checkpoint_owner_can_approve_write_tools(monkeypatch) -> None:
    from src.agent.state import ToolResult
    from src.tools.registry import ToolRegistry

    calls = []

    async def call(self, name, args):
        calls.append((name, args))
        return ToolResult(name=name, args=args, ok=True, output={"status": "created"})

    monkeypatch.setattr(ToolRegistry, "call", call)
    runner = GraphRunner(Settings(_env_file=None))
    collector = Collector()
    await runner.run(
        "owned-approval", "帮我建工单", collector, user_id="alice",
        pending_calls=[{"name": "create_ticket", "args": {"title": "Private"}}],
    )
    assert await runner.awaiting_approval("owned-approval")
    assert calls == []
    with pytest.raises(PermissionError):
        await runner.resume("owned-approval", {"ok": True}, collector, user_id="bob")
    assert calls == []
    await runner.resume("owned-approval", {"ok": True}, collector, user_id="alice")
    assert calls == [("create_ticket", {"title": "Private"})]
    assert not await runner.awaiting_approval("owned-approval")
    assert collector.types[-1] == "done"


async def test_each_write_tool_needs_separate_confirmation(monkeypatch) -> None:
    from src.agent.state import ToolResult
    from src.tools.registry import ToolRegistry

    calls = []

    async def call(self, name, args):
        calls.append(args["title"])
        return ToolResult(name=name, args=args, ok=True)

    monkeypatch.setattr(ToolRegistry, "call", call)
    runner = GraphRunner(Settings(_env_file=None))
    collector = Collector()
    await runner.run(
        "two-approvals", "帮我建工单", collector, user_id="alice",
        pending_calls=[
            {"name": "create_ticket", "args": {"title": "First"}},
            {"name": "create_ticket", "args": {"title": "Second"}},
        ],
    )
    await runner.resume("two-approvals", {"ok": True}, collector, user_id="alice")
    assert await runner.awaiting_approval("two-approvals")
    assert calls == []
    await runner.resume("two-approvals", {"ok": False}, collector, user_id="alice")
    assert not await runner.awaiting_approval("two-approvals")
    assert calls == ["First"]
