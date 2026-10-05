"""Session revocation must close SSE and release its subscription."""

import pytest

from apps.api.src import sse
from apps.api.src.schemas.events import make_event


async def test_revocation_closes_stream_before_more_events(monkeypatch):
    clock = 0
    allowed = True

    async def authorized():
        return allowed

    monkeypatch.setattr(sse, "monotonic", lambda: clock)
    bus = sse.EventBus()
    bus.publish(make_event(type="token", run_id="private", payload={"delta": "first"}))
    stream = sse.sse_stream("private", event_bus=bus, authorized=authorized)
    assert "retry:" in await anext(stream)
    assert "first" in await anext(stream)
    allowed = False
    clock = sse.HEARTBEAT_S
    bus.publish(make_event(type="token", run_id="private", payload={"delta": "secret"}))
    frame = await anext(stream)
    assert "auth_expired" in frame
    assert "secret" not in frame
    await stream.aclose()
    assert "private" not in bus._subscribers


async def test_closing_stream_after_first_frame_releases_subscription():
    bus = sse.EventBus()
    stream = sse.sse_stream("private", event_bus=bus)
    await anext(stream)
    await stream.aclose()
    assert "private" not in bus._subscribers


async def test_auth_deadline_is_preserved_when_events_arrive_between_heartbeats(monkeypatch):
    clock = 0
    waits = []

    async def authorized():
        return True

    async def timeout(awaitable, timeout):
        awaitable.close()
        waits.append(timeout)
        raise TimeoutError

    monkeypatch.setattr(sse, "monotonic", lambda: clock)
    bus = sse.EventBus()
    bus.publish(make_event(type="token", run_id="private", payload={"delta": "first"}))
    stream = sse.sse_stream("private", event_bus=bus, authorized=authorized)
    await anext(stream)
    await anext(stream)
    clock = sse.HEARTBEAT_S - 1
    monkeypatch.setattr(sse.asyncio, "wait_for", timeout)
    assert '"type":"ping"' in await anext(stream)
    assert waits == [pytest.approx(1)]
    await stream.aclose()
