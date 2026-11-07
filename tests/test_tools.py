"""M3 工具层：Schema、风险分级、超时重试、幂等键。"""

from __future__ import annotations

import pytest

from src.config import Settings
from src.tools.registry import ToolRegistry


def _registry() -> ToolRegistry:
    return ToolRegistry(Settings(_env_file=None))


def test_specs_expose_json_schema_for_function_calling() -> None:
    registry = _registry()
    payload = registry.specs_payload()
    names = {item["function"]["name"] for item in payload}
    assert {"search_code", "query_metrics", "create_ticket", "draft_report"} == names
    for item in payload:
        assert item["function"]["parameters"]["type"] == "object"


def test_risk_classification() -> None:
    registry = _registry()
    assert registry.is_high_risk("create_ticket") is True
    assert registry.is_high_risk("search_code") is False


@pytest.mark.parametrize(
    ("query", "severity"),
    [("创建P0工单", "P0"), ("帮我建一个p1工单", "P1"), ("创建P10工单", "P2")],
)
def test_ticket_priority_in_chinese_requests(query, severity) -> None:
    from src.agent.nodes.tools import _planned_calls

    ticket = next(
        call
        for call in _planned_calls(
            {
                "intent": "ticket",
                "query": query,
                "requested_tools": ["create_ticket"],
            }
        )
        if call["name"] == "create_ticket"
    )
    assert ticket["args"] == {"title": query, "detail": query, "severity": severity}


def test_confirmation_uses_previous_ticket_draft_as_write_payload() -> None:
    from src.agent.nodes.tools import _planned_calls

    calls = _planned_calls(
        {
            "intent": "ticket",
            "query": "确认创建，按刚才的 P1 草稿创建工单。",
            "requested_tools": ["create_ticket"],
            "ticket_confirmation": True,
            "conversation_history": [
                {
                    "run_id": "draft-run-1",
                    "status": "completed",
                    "query": "将刚才工单优先级改为 P1，但先不要创建，等我确认。",
                    "answer": (
                        "已生成待确认草稿。\n\n"
                        "标题：DemoShop 订单服务故障跟进。\n"
                        "优先级：P1（待确认）。\n\n"
                        "描述：\n"
                        "现象与证据：订单服务 5xx 与延迟升高。\n"
                        "调查判断：根因仍待确认。\n"
                        "当前状态：仅生成文本草稿，未调用工具。\n"
                        "你可以在下一轮单独回复‘确认创建’。"
                    ),
                    "tool_results": [],
                    "plan": {"steps": [{"kind": "answer", "status": "done"}]},
                }
            ],
        }
    )

    ticket = next(call for call in calls if call["name"] == "create_ticket")
    assert ticket["args"] == {
        "title": "DemoShop 订单服务故障跟进。",
        "detail": "现象与证据：订单服务 5xx 与延迟升高。\n调查判断：根因仍待确认。",
        "severity": "P1",
    }


def test_confirmation_uses_most_recent_unwritten_draft_from_history() -> None:
    from src.agent.nodes.tools import _ticket_draft_from_history

    state = {
        "conversation_history": [
            {
                "run_id": "older-draft",
                "status": "completed",
                "answer": "标题：旧草稿\n优先级：P2\n描述：\n旧内容\n当前状态：等待确认",
                "tool_results": [],
                "plan": {"steps": []},
            },
            {
                "run_id": "already-written",
                "status": "completed",
                "answer": "标题：已创建工单\n优先级：P1\n描述：\n已写入内容",
                "tool_results": [{"name": "create_ticket", "ok": True}],
            },
            {
                "run_id": "latest-draft",
                "status": "completed",
                "answer": "标题：新草稿\n优先级：P1\n描述：\n新内容\n当前状态：仅生成草稿",
                "tool_results": [],
                "plan": {"steps": []},
            },
        ]
    }

    draft = _ticket_draft_from_history(state)

    assert draft is not None
    assert draft["run_id"] == "latest-draft"
    assert draft["title"] == "新草稿"
    assert draft["detail"] == "新内容"
    assert draft["severity"] == "P1"
    assert draft["fingerprint"]


def test_confirmation_ignores_incomplete_or_noncompleted_history() -> None:
    from src.agent.nodes.tools import _ticket_draft_from_history

    state = {
        "conversation_history": [
            {
                "run_id": "incomplete",
                "status": "completed",
                "answer": "标题：不完整\n优先级：P1\n描述：\n",
                "tool_results": [],
            },
            {
                "run_id": "failed",
                "status": "failed",
                "answer": "标题：失败草稿\n优先级：P1\n描述：\n不可用",
                "tool_results": [],
            },
        ]
    }

    assert _ticket_draft_from_history(state) is None


def test_confirmation_without_previous_ticket_draft_does_not_write_confirmation_text() -> None:
    from src.agent.nodes.tools import _planned_calls

    calls = _planned_calls(
        {
            "intent": "ticket",
            "query": "确认创建，按刚才的 P1 草稿创建工单。",
            "requested_tools": ["create_ticket"],
            "ticket_confirmation": True,
            "conversation_history": [],
        }
    )

    assert not any(call["name"] == "create_ticket" for call in calls)




async def test_read_tool_returns_structured_result() -> None:
    registry = _registry()
    result = await registry.call("query_metrics", {"service": "order-service", "window": "1h"})
    assert result.ok is True
    assert result.risk == "read"
    assert result.output["service"] == "order-service"  # type: ignore[index]


def test_answer_tool_summary_preserves_complete_metrics_result():
    from src.agent.nodes.answer import _build_tool_summary

    summary = _build_tool_summary(
        {
            "tool_results": [
                {
                    "name": "query_metrics",
                    "ok": True,
                    "output": {
                        "service": "order-service",
                        "window": "1h",
                        "note": "样例指标数据，不代表实时监控结果",
                        "series": [
                            {"metric": "http_5xx_rate", "points": [0.002, 0.019, 0.058]},
                            {"metric": "p99_latency_ms", "points": [220, 480, 1250, 1100, 690]},
                            {"metric": "db_pool_usage", "points": [0.45, 0.72, 0.96, 0.94, 0.77]},
                            {"metric": "complete_after_old_limit", "points": ["x" * 2400]},
                        ],
                    },
                }
            ],
        }
    )

    assert '"metric": "p99_latency_ms"' in summary
    assert '"points": [220, 480, 1250, 1100, 690]' in summary
    assert '"metric": "db_pool_usage"' in summary
    assert '"note": "样例指标数据，不代表实时监控结果"' in summary
    assert '"metric": "complete_after_old_limit"' in summary


async def test_search_code_actually_greps_repository() -> None:
    registry = _registry()
    result = await registry.call("search_code", {"query": "ToolRegistry", "top_k": 3})
    assert result.ok is True
    assert result.output["count"] >= 1  # type: ignore[index]


async def test_ticket_tool_cannot_fake_success_without_approval() -> None:
    from src.agent.context import bind

    bind(write_approved=False, user_id="", run_id="")
    registry = _registry()
    args = {"title": "订单服务 5xx 排查", "severity": "P1", "idempotency_key": "k-1"}
    first = await registry.call("create_ticket", dict(args))
    assert first.ok is False
    assert first.output is None
    assert "approval" in first.error


async def test_unknown_tool_returns_error_result() -> None:
    registry = _registry()
    result = await registry.call("not_exists", {})
    assert result.ok is False
    assert "未注册" in (result.error or "")


async def test_ticket_tool_without_database_returns_failure(monkeypatch) -> None:
    import uuid

    from src.agent.context import bind

    bind(
        write_approved=True,
        user_id=str(uuid.uuid4()),
        run_id=str(uuid.uuid4()),
        settings=Settings(_env_file=None),
    )
    monkeypatch.setattr("src.db.session.get_session_factory", lambda _settings: None)
    try:
        result = await _registry().call(
            "create_ticket",
            {
                "title": "Valid title",
                "idempotency_key": "operation",
            },
        )
        assert result.ok is False
        assert result.output is None
        assert "database" in result.error
    finally:
        bind(write_approved=False, user_id="", run_id="")


async def test_same_idempotency_key_never_shares_outputs_between_users() -> None:
    from src.agent.context import bind, get

    registry = _registry()
    calls = []

    def execute(args):
        calls.append(get("user_id"))
        return {"private_owner": get("user_id")}

    registry.specs["draft_report"].idempotent = True
    registry.executors["draft_report"] = execute
    args = {"title": "Same title"}
    try:
        bind(user_id="alice", write_approved=True)
        first = await registry.call("draft_report", args)
        assert (await registry.call("draft_report", args)).output == first.output
        bind(user_id="bob", write_approved=True)
        second = await registry.call("draft_report", args)
        assert first.output == {"private_owner": "alice"}
        assert second.output == {"private_owner": "bob"}
        assert calls == ["alice", "bob"]
    finally:
        bind(user_id="", write_approved=False)


async def test_invalid_arguments_never_enter_executor() -> None:
    registry = _registry()

    def execute(args):
        raise AssertionError("invalid arguments entered executor")

    registry.executors["search_code"] = execute
    result = await registry.call("search_code", {"query": "x", "top_k": 0})
    assert not result.ok
    assert "Invalid arguments" in result.error


async def test_sync_executor_does_not_block_event_loop() -> None:
    import asyncio
    import time

    registry = _registry()
    reached = asyncio.Event()

    def execute(args):
        time.sleep(0.15)
        return {"completed": reached.is_set()}

    async def tick():
        await asyncio.sleep(0.01)
        reached.set()

    registry.executors["search_code"] = execute
    result, _ = await asyncio.gather(registry.call("search_code", {"query": "x"}), tick())
    assert result.output["completed"]


async def test_write_timeout_never_automatically_retries() -> None:
    import asyncio
    import time

    from src.agent.context import bind

    registry = _registry()
    calls = []

    def execute(args):
        calls.append(args)
        time.sleep(0.05)
        return {"committed": True}

    registry.executors["draft_report"] = execute
    registry.specs["draft_report"].timeout_s = 0.01
    registry.specs["draft_report"].retries = 3
    bind(write_approved=True)
    try:
        result = await registry.call("draft_report", {"title": "x"})
        assert not result.ok
        await asyncio.sleep(0.08)
        assert len(calls) == 1
    finally:
        bind(write_approved=False)


async def test_read_retries_respect_attempt_budget() -> None:
    registry = _registry()
    calls = []

    def execute(args):
        calls.append(args)
        raise RuntimeError("temporarily unavailable")

    registry.executors["query_metrics"] = execute
    result = await registry.call("query_metrics", {"service": "orders"}, max_attempts=1)
    assert not result.ok
    assert result.attempts == len(calls) == 1
