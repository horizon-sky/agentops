"""M3 工具层：Schema、风险分级、超时重试、幂等键。"""

from __future__ import annotations

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


async def test_write_tool_is_idempotent() -> None:
    registry = _registry()
    args = {"title": "订单服务 5xx 排查", "severity": "P1", "idempotency_key": "k-1"}
    first = await registry.call("create_ticket", dict(args))
    second = await registry.call("create_ticket", dict(args))
    assert first.ok and second.ok
    assert first.output["ticket_id"] == second.output["ticket_id"]  # type: ignore[index]


async def test_unknown_tool_returns_error_result() -> None:
    registry = _registry()
    result = await registry.call("not_exists", {})
    assert result.ok is False
    assert "未注册" in (result.error or "")


async def test_same_idempotency_key_never_shares_outputs_between_users() -> None:
    from src.agent.context import bind, get

    registry = _registry()
    calls = []

    def execute(args):
        calls.append(get("user_id"))
        return {"private_owner": get("user_id")}

    registry.executors["create_ticket"] = execute
    args = {"title": "Same title", "idempotency_key": "same-key"}
    try:
        bind(user_id="alice")
        first = await registry.call("create_ticket", args)
        assert (await registry.call("create_ticket", args)).output == first.output
        bind(user_id="bob")
        second = await registry.call("create_ticket", args)
        assert first.output == {"private_owner": "alice"}
        assert second.output == {"private_owner": "bob"}
        assert calls == ["alice", "bob"]
    finally:
        bind(user_id="")
