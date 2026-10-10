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
        for call in _planned_calls({"intent": "ticket", "query": query})
        if call["name"] == "create_ticket"
    )
    assert ticket["args"] == {"title": query, "detail": query, "severity": severity}


async def test_read_tool_returns_structured_result() -> None:
    registry = _registry()
    result = await registry.call("query_metrics", {"service": "order-service", "window": "1h"})
    assert result.ok is True
    assert result.risk == "read"
    assert result.output["service"] == "order-service"  # type: ignore[index]


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
