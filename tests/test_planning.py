"""Policy, dependency execution and bounded supplementation regressions."""

from __future__ import annotations

import asyncio

import pytest

from src.agent.model import ModelResult
from src.agent.nodes.classify import IntentOut
from src.agent.nodes.review import ReviewOut
from src.agent.planning import ExecutionPlan, PlanStep, static_plan, validate_plan
from src.agent.runner import GraphRunner
from src.config import Settings
from src.tools.registry import ToolRegistry
from tests.test_graph import Collector


@pytest.mark.parametrize(
    ("intent", "tools", "retrieve"),
    [
        ("knowledge", [], True),
        ("code", ["search_code"], False),
        ("general", [], False),
        ("ticket", ["search_code", "create_ticket"], True),
        ("incident", ["query_metrics", "search_code"], True),
    ],
)
def test_static_routes(intent, tools, retrieve):
    state = {"intent": intent, "query": "问题", "flags": {"routing": True}}
    plan = static_plan(state)
    validate_plan(plan, state, ToolRegistry(Settings(_env_file=None)))
    assert [s.tool for s in plan.steps if s.kind == "tool"] == tools
    assert any(s.kind == "retrieve" for s in plan.steps) == retrieve


def test_cycles_and_unauthorized_tools_are_rejected():
    state = {"intent": "general", "query": "你好", "flags": {"routing": True}}
    registry = ToolRegistry(Settings(_env_file=None))
    for plan in [
        ExecutionPlan(
            steps=[PlanStep(id="answer", kind="answer", goal="x", depends_on=["answer"])]
        ),
        ExecutionPlan(
            steps=[
                PlanStep(
                    id="write", kind="tool", goal="x", tool="create_ticket", args={"title": "x"}
                ),
                PlanStep(id="answer", kind="answer", goal="x", depends_on=["write"]),
            ]
        ),
    ]:
        with pytest.raises(ValueError):
            validate_plan(plan, state, registry)


async def test_general_skips_evidence():
    collector = Collector()
    runner = GraphRunner(Settings(_env_file=None, agent_conditional_routing=True))
    await runner.run("general-route", "你好", collector)
    assert "tool_result" not in collector.types
    assert "retrieve" not in collector.types
    skipped = [e.stage for e in collector.events if (e.payload or {}).get("status") == "skipped"]
    assert skipped == ["retrieve", "tools"]


async def test_stale_approval_cannot_execute():
    collector = Collector()
    runner = GraphRunner(Settings(_env_file=None))
    await runner.run("stale-approval", "建工单", collector, user_id="alice")
    with pytest.raises(ValueError, match="approval_id"):
        await runner.resume(
            "stale-approval", {"ok": True, "approval_id": "old"}, collector, user_id="alice"
        )
    assert await runner.awaiting_approval("stale-approval")
    assert collector.payload_of("hitl_request")["approval_id"] == "stale-approval:tool-1"
    with pytest.raises(ValueError, match="approval_id"):
        await runner.resume("stale-approval", {"ok": True}, collector, user_id="alice")


def test_retrieval_arguments_and_premature_write_are_rejected():
    state = {"intent": "ticket", "query": "建单", "flags": {"routing": True}}
    registry = ToolRegistry(Settings(_env_file=None))
    invalid = static_plan(state)
    invalid.steps[0].args = {"query": []}
    with pytest.raises(ValueError):
        validate_plan(invalid, state, registry)
    invalid = static_plan(state)
    invalid.steps[2].depends_on = ["retrieve"]
    with pytest.raises(ValueError, match="evidence"):
        validate_plan(invalid, state, registry)


async def test_invalid_dynamic_plan_falls_back_without_extra_tools():
    class InvalidPlanner(GapLLM):
        async def acomplete(self, messages, tier="cheap", response_model=None):
            if response_model is IntentOut:
                return ModelResult(parsed=IntentOut(intent="general"))
            if response_model is ExecutionPlan:
                return ModelResult(parsed=ExecutionPlan(steps=[
                    PlanStep(id="answer", kind="answer", goal="x", depends_on=["answer"]),
                ]))
            return await super().acomplete(messages, tier, response_model)

    settings = Settings(_env_file=None, agent_conditional_routing=True, agent_dynamic_plan=True)
    runner, collector = GraphRunner(settings), Collector()
    runner.llm = InvalidPlanner()
    await runner.run("invalid-dynamic", "你好", collector)
    assert "tool_result" not in collector.types
    assert "retrieve" not in collector.types
    assert collector.payload_of("done")["plan"]["steps"][0]["id"] == "answer"


class GapLLM:
    async def acomplete(self, messages, tier="cheap", response_model=None):
        if response_model is IntentOut:
            return ModelResult(parsed=IntentOut(intent="code"))
        if response_model is ReviewOut:
            return ModelResult(
                parsed=ReviewOut(
                    sufficient=False,
                    reason="缺少实现细节",
                    missing_evidence=["实现代码"],
                    next_action="tools",
                    query="ToolRegistry",
                )
            )
        return ModelResult()

    async def astream(self, messages, tier="strong"):
        yield "证据仍有不足"


async def test_supplement_preserves_results_and_stops_no_progress():
    from src.agent.graph import build_graph

    settings = Settings(_env_file=None, agent_conditional_routing=True, agent_targeted_retry=True)
    runner, collector = GraphRunner(settings), Collector()
    runner.llm = GapLLM()
    await runner.run("gap-run", "查找代码", collector)
    graph, _ = await build_graph(settings, runner.llm)
    state = (await graph.aget_state({"configurable": {"thread_id": "gap-run"}})).values
    assert state["retry"] <= 2
    assert len(state["tool_results"]) >= 2
    assert state["review"]["sufficient"] is False
    assert state["review"]["next_action"] == "answer"
    assert len({r["step_id"] for r in state["tool_results"]}) == len(state["tool_results"])


async def test_missing_database_does_not_repeat_retrieval():
    class MissingLibrary(GapLLM):
        async def acomplete(self, messages, tier="cheap", response_model=None):
            if response_model is IntentOut:
                return ModelResult(parsed=IntentOut(intent="knowledge"))
            if response_model is ReviewOut:
                return ModelResult(parsed=ReviewOut(
                    sufficient=False, missing_evidence=["文档"],
                    next_action="retrieve", query="规范",
                ))
            return ModelResult()

    runner = GraphRunner(Settings(
        _env_file=None, agent_conditional_routing=True, agent_targeted_retry=True,
    ))
    runner.llm = MissingLibrary()
    collector = Collector()
    await runner.run("missing-library", "知识库规范", collector)
    assert collector.types.count("retrieve") == 1
    assert collector.payload_of("done")["review"]["sufficient"] is False
    assert "证据不足" in collector.payload_of("done")["answer"]


@pytest.mark.parametrize(("query", "report"), [
    ("解释报告模板", False), ("报告在哪里", False),
    ("生成处理报告", True), ("Please draft a report", True),
])
def test_report_requires_explicit_creation_request(query, report):
    plan = static_plan({"intent": "general", "query": query, "flags": {"routing": True}})
    assert any(s.tool == "draft_report" for s in plan.steps) is report


async def test_execution_timeout_finalizes_with_insufficient_evidence():
    class SlowLLM(GapLLM):
        async def acomplete(self, messages, tier="cheap", response_model=None):
            if response_model is ReviewOut:
                await asyncio.sleep(1)
            return await super().acomplete(messages, tier, response_model)

    runner = GraphRunner(Settings(
        _env_file=None, agent_conditional_routing=True, agent_max_execution_s=0.05,
    ))
    runner.llm = SlowLLM()
    collector = Collector()
    await runner.run("execution-timeout", "查找代码", collector)
    result = collector.payload_of("done")
    assert result["review"]["sufficient"] is False
    assert result["review"]["stop_reason"] == "execution_budget"
    assert "证据不足" in result["answer"]


async def test_parallel_read_retries_share_global_budget(monkeypatch):
    from src.agent.graph import build_graph

    settings = Settings(
        _env_file=None, agent_conditional_routing=True, agent_max_read_calls=2,
    )
    registry = ToolRegistry(settings)
    calls = []

    def unavailable(args):
        calls.append(args)
        raise RuntimeError("offline")

    registry.executors["search_code"] = unavailable
    registry.executors["query_metrics"] = unavailable
    monkeypatch.setattr("src.tools.registry._registry", registry)
    runner, collector = GraphRunner(settings), Collector()
    await runner.run("read-budget", "排查服务报警", collector)
    graph, _ = await build_graph(settings, runner.llm)
    snapshot = await graph.aget_state({"configurable": {"thread_id": "read-budget"}})
    assert snapshot.values["read_calls"] == len(calls) == 2
    assert {result["name"] for result in snapshot.values["tool_results"]} == {
        "search_code", "query_metrics",
    }
