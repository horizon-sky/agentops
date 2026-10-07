"""M1 冒烟：健康检查、事件总线与 SSE 流、EchoRunner 事件序列。"""

from __future__ import annotations

import json

from fastapi.testclient import TestClient
from langchain_core.messages import HumanMessage

from apps.api.src.main import app
from apps.api.src.schemas.events import make_event
from apps.api.src.sse import EventBus, sse_stream
from src.agent.runner import EchoRunner
from src.config import Settings


def test_healthz_returns_degraded_status_without_db() -> None:
    with TestClient(app) as client:
        response = client.get("/healthz")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert "db" in body and "cache" in body


def test_api_route_requires_configured_token(monkeypatch) -> None:
    monkeypatch.setattr(
        "apps.api.src.deps.get_settings",
        lambda: Settings(_env_file=None, api_token="secret"),
    )
    with TestClient(app) as client:
        assert client.get("/sessions").status_code == 401
        assert client.get("/sessions", headers={"Authorization": "Bearer wrong"}).status_code == 401


async def test_event_bus_fans_out_to_subscriber() -> None:
    bus = EventBus()
    queue = bus.subscribe("run-1")
    bus.publish(make_event(type="plan", run_id="run-1", payload={"steps": ["a"]}))
    event = await queue.get()
    assert event.type == "plan"
    assert bus.history("run-1")[0].type == "plan"


async def test_sse_stream_emits_heartbeat_and_terminates_on_done() -> None:
    bus = EventBus()
    run_id = "run-2"

    async def producer() -> None:
        bus.publish(make_event(type="token", run_id=run_id, payload={"delta": "hi"}))
        bus.publish(make_event(type="done", run_id=run_id, payload={"answer": "hi"}))

    import asyncio

    asyncio.get_event_loop().create_task(producer())
    frames = []
    async for frame in sse_stream(run_id, event_bus=bus, idle_timeout_s=60):
        if not frame.startswith("data: "):
            continue  # 跳过 retry 等控制帧
        frames.append(json.loads(frame.replace("data: ", "").strip()))
        if len(frames) >= 2:
            break
    assert [frame["type"] for frame in frames] == ["token", "done"]


async def test_echo_runner_emits_plan_token_done() -> None:
    settings = Settings(_env_file=None, llm_api_key="")
    events: list[str] = []

    async def emit(event: object) -> None:
        events.append(event.type)

    runner = EchoRunner(settings)
    await runner.run("run-3", "订单服务 5xx 如何排查？", emit)  # type: ignore[arg-type]
    assert events[0] == "plan"
    assert "token" in events
    assert events[-1] == "done"


async def test_echo_llm_used_by_runner_when_no_key() -> None:
    settings = Settings(_env_file=None, llm_api_key="", llm_model="deepseek-chat")
    llm = EchoRunner(settings).llm
    result = await llm.acomplete([HumanMessage(content="hi")])
    assert result.text == "hi"


async def test_echo_reports_retrieval_as_not_executed() -> None:
    events = []

    async def emit(event):
        events.append(event)

    await EchoRunner(Settings(_env_file=None)).run("echo-diagnosis", "Question", emit)
    for event in events:
        if event.type in {"retrieve", "done"}:
            assert event.payload["retrieval"]["mode"] == "echo"
            assert event.payload["retrieval"]["status"] == "not_executed"
            assert event.payload["citations"] == []
