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
        ("ticket", [], True),
        ("incident", [], True),
    ],
)
def test_static_routes(intent, tools, retrieve):
    query = "incident" if intent == "incident" else "问题"
    state = {
        "intent": intent,
        "query": query,
        "requested_tools": ["search_code"] if intent == "code" else [],
        "flags": {"routing": True},
    }
    plan = static_plan(state)
    validate_plan(plan, state, ToolRegistry(Settings(_env_file=None)))
    assert [s.tool for s in plan.steps if s.kind == "tool"] == tools
    assert any(s.kind == "retrieve" for s in plan.steps) == retrieve


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        (
            "根据现有信息拟一张 P2 跟进工单，先展示标题、描述和优先级，等待我确认后再创建。",
            ["create_ticket"],
        ),
        ("将刚才工单优先级改为 P1，但先不要创建，等我确认。", []),
        ("目前没有发布记录、日志和 Trace。请给出下一步排查清单。", []),
    ],
)
def test_ticket_tool_plan_follows_classifier_selection(query, expected):
    state = {
        "intent": "ticket",
        "query": query,
        "requested_tools": expected,
        "flags": {"routing": True},
    }
    plan = static_plan(state)
    assert [step.tool for step in plan.steps if step.kind == "tool"] == expected


def test_dynamic_plan_cannot_add_unrequested_metrics_tool():
    state = {
        "intent": "incident",
        "query": "这组指标能否证明数据库连接池是故障根因？",
        "flags": {"routing": True},
    }
    plan = ExecutionPlan(
        steps=[
            PlanStep(id="retrieve", kind="retrieve", goal="检索", args={"query": state["query"]}),
            PlanStep(
                id="metrics",
                kind="tool",
                goal="指标",
                tool="query_metrics",
                args={"service": "order-service", "window": "1h"},
                depends_on=["retrieve"],
            ),
            PlanStep(id="answer", kind="answer", goal="回答", depends_on=["retrieve", "metrics"]),
        ]
    )

    with pytest.raises(ValueError, match="Tool outside intent policy"):
        validate_plan(plan, state, ToolRegistry(Settings(_env_file=None)))


def test_dynamic_plan_cannot_replace_confirmed_ticket_draft_with_confirmation_text():
    state = {
        "intent": "ticket",
        "query": "确认创建",
        "requested_tools": ["create_ticket"],
        "ticket_confirmation": True,
        "conversation_history": [
            {
                "query": "创建跟进草稿",
                "answer": (
                    "标题：订单服务故障跟进\n优先级：P1（待确认）\n\n"
                    "描述：\n订单服务 5xx 升高，根因待确认。\n"
                    "请确认是否按以上草稿创建。"
                ),
            }
        ],
        "flags": {"routing": True},
    }
    plan = ExecutionPlan(
        steps=[
            PlanStep(id="retrieve", kind="retrieve", goal="检索", args={"query": "确认创建"}),
            PlanStep(
                id="write",
                kind="tool",
                goal="create_ticket",
                tool="create_ticket",
                args={"title": "确认创建", "detail": "确认创建", "severity": "P1"},
                depends_on=["retrieve"],
            ),
            PlanStep(id="answer", kind="answer", goal="回答", depends_on=["retrieve", "write"]),
        ]
    )

    validated = validate_plan(plan, state, ToolRegistry(Settings(_env_file=None)))

    write = next(step for step in validated.steps if step.tool == "create_ticket")
    assert write.args == {
        "title": "订单服务故障跟进",
        "detail": "订单服务 5xx 升高，根因待确认。",
        "severity": "P1",
    }


def test_incident_tool_selection_requires_classifier_authorization():
    query = "这组指标能否证明数据库连接池是故障根因？"
    state = {"intent": "incident", "query": query, "flags": {"routing": True}}
    assert not any(step.kind == "tool" for step in static_plan(state).steps)

    state["requested_tools"] = ["query_metrics"]
    plan = static_plan(state)
    assert [step.tool for step in plan.steps if step.kind == "tool"] == ["query_metrics"]


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
    await runner.run(
        "stale-approval",
        "建工单",
        collector,
        pending_calls=[{"name": "create_ticket", "args": {"title": "建工单"}}],
        user_id="alice",
    )
    with pytest.raises(ValueError, match="approval_id"):
        await runner.resume(
            "stale-approval", {"ok": True, "approval_id": "old"}, collector, user_id="alice"
        )
    assert await runner.awaiting_approval("stale-approval")
    assert collector.payload_of("hitl_request")["approval_id"] == "stale-approval:tool-0"
    with pytest.raises(ValueError, match="approval_id"):
        await runner.resume("stale-approval", {"ok": True}, collector, user_id="alice")


def test_retrieval_arguments_and_premature_write_are_rejected():
    state = {
        "intent": "ticket",
        "query": "建单",
        "requested_tools": ["create_ticket"],
        "flags": {"routing": True},
    }
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


def test_tool_selection_is_limited_to_classifier_authorization():
    state = {
        "intent": "ticket",
        "query": "解释报告模板，不要创建工单",
        "requested_tools": ["draft_report", "query_metrics", "create_ticket"],
        "flags": {"routing": True},
    }
    plan = static_plan(state)
    assert [step.tool for step in plan.steps if step.kind == "tool"] == [
        "draft_report",
        "query_metrics",
        "create_ticket",
    ]
    state["intent"] = "knowledge"
    assert not any(step.kind == "tool" for step in static_plan(state).steps)


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

    class IncidentLLM:
        async def acomplete(self, messages, tier="cheap", response_model=None):
            if response_model is IntentOut:
                return ModelResult(
                    parsed=IntentOut(
                        intent="incident", requested_tools=["query_metrics", "search_code"]
                    )
                )
            if response_model is ReviewOut:
                return ModelResult(parsed=ReviewOut(sufficient=False))
            return ModelResult()

        async def astream(self, messages, tier="strong"):
            yield "证据不足"

    runner.llm = IncidentLLM()
    await runner.run("read-budget", "查询故障指标并搜索源码", collector)
    graph, _ = await build_graph(settings, runner.llm)
    snapshot = await graph.aget_state({"configurable": {"thread_id": "read-budget"}})
    assert snapshot.values["read_calls"] == len(calls) == 2
    assert {result["name"] for result in snapshot.values["tool_results"]} == {
        "search_code", "query_metrics",
    }
