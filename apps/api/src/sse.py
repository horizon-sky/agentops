"""按 run_id 分发的事件总线与 SSE 广播。

同一个 run 的事件既推给在线订阅者（SSE），也保留一份历史，
便于断线重连后的回放，以及 M6 评测阶段离线分析。
"""

from __future__ import annotations

import asyncio
from collections import defaultdict

from apps.api.src.schemas.events import AgentEvent, make_event

HEARTBEAT_S = 15
DEFAULT_HISTORY_LIMIT = 500


class EventBus:
    def __init__(self, history_limit: int = DEFAULT_HISTORY_LIMIT) -> None:
        self._subscribers: dict[str, set[asyncio.Queue[AgentEvent]]] = defaultdict(set)
        self._history: dict[str, list[AgentEvent]] = defaultdict(list)
        self._history_limit = history_limit

    def subscribe(self, run_id: str, replay: bool = True) -> asyncio.Queue[AgentEvent]:
        """订阅事件。

        replay=True 时先把已有历史灌入队列，解决两个真实问题：
        1. 客户端先创建 run 再连接 SSE 时，早期事件不会丢失；
        2. 断线重连后可补全中间事件。
        """
        queue: asyncio.Queue[AgentEvent] = asyncio.Queue()
        if replay:
            for event in self._history.get(run_id, ()):
                queue.put_nowait(event)
        self._subscribers[run_id].add(queue)
        return queue

    def unsubscribe(self, run_id: str, queue: asyncio.Queue[AgentEvent]) -> None:
        self._subscribers[run_id].discard(queue)
        if not self._subscribers[run_id]:
            self._subscribers.pop(run_id, None)

    def publish(self, event: AgentEvent) -> None:
        history = self._history[event.run_id]
        history.append(event)
        if len(history) > self._history_limit:
            del history[: len(history) - self._history_limit]

        for queue in list(self._subscribers.get(event.run_id, ())):
            queue.put_nowait(event)

    def history(self, run_id: str) -> list[AgentEvent]:
        return list(self._history.get(run_id, []))

    def clear(self, run_id: str) -> None:
        self._history.pop(run_id, None)


default_bus = EventBus()
# 兼容旧引用的模块级总线（路由层与执行器共用）
bus = default_bus


def emit(run_id: str, event: AgentEvent) -> None:
    default_bus.publish(event)


async def sse_stream(
    run_id: str,
    event_bus: EventBus | None = None,
    idle_timeout_s: int = 900,
):
    """SSE 生成器：转发事件，空闲时发心跳，遇到 done/error 结束。"""
    event_bus = event_bus or default_bus
    queue = event_bus.subscribe(run_id)
    elapsed = 0
    yield "retry: 3000\n\n"
    try:
        while elapsed < idle_timeout_s:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=HEARTBEAT_S)
            except TimeoutError:
                elapsed += HEARTBEAT_S
                yield make_event(type="ping", run_id=run_id).to_sse()
                continue
            yield event.to_sse()
            if event.type in ("done", "error"):
                break
    finally:
        event_bus.unsubscribe(run_id, queue)
