"""前后端共享的 SSE 事件协议（单一事实来源，前端据此生成 TS 类型）。"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

EventType = Literal[
    "plan",
    "retrieve",
    "tool_result",
    "hitl_request",
    "token",
    "done",
    "error",
    "ping",
]
Stage = Literal["plan", "retrieve", "tools", "generate"]


class AgentEvent(BaseModel):
    """一次 Agent 执行中的原子事件。

    - type：事件类型
    - stage：所属阶段，error 事件必带，用于前端定位失败发生在规划/检索/工具/生成哪一段
    - ms：该步骤耗时，用于执行时间线与成本瀑布图
    """

    id: str = Field(default_factory=lambda: uuid4().hex)
    type: EventType
    run_id: str
    payload: dict[str, Any] | None = None
    stage: Stage | None = None
    ms: int | None = None
    ts: datetime = Field(default_factory=lambda: datetime.now(UTC))

    def to_sse(self) -> str:
        return f"data: {self.model_dump_json()}\n\n"


def make_event(
    *,
    type: EventType,
    run_id: str,
    payload: dict[str, Any] | None = None,
    stage: Stage | None = None,
    ms: int | None = None,
) -> AgentEvent:
    return AgentEvent(type=type, run_id=run_id, payload=payload, stage=stage, ms=ms)
