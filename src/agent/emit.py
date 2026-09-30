"""节点内事件发送：优先从上下文取 emit 回调，回退到 LangGraph configurable。"""

from __future__ import annotations

from typing import Any

from apps.api.src.schemas.events import AgentEvent, make_event
from src.agent.context import get as ctx_get


def get_emit(config: Any | None = None):
    emit = ctx_get("emit")
    if emit is None and config is not None:
        emit = (config.get("configurable") or {}).get("emit")

    async def _emit(event: AgentEvent) -> None:
        if emit is not None:
            await emit(event)

    return _emit


def event_of(
    *,
    type: str,
    run_id: str,
    payload: dict[str, Any] | None = None,
    stage: str | None = None,
    ms: int | None = None,
) -> AgentEvent:
    return make_event(type=type, run_id=run_id, payload=payload, stage=stage, ms=ms)  # type: ignore[arg-type]
