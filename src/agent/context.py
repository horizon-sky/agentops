"""节点上下文：用 contextvars 传递 settings / llm / emit。

LangGraph 的 RunnableConfig 只保证传递已知字段，自定义 configurable 键可能被过滤，
因此改用 contextvars —— 在异步任务内天然隔离，且不必把依赖塞进状态里。
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any

_ctx: ContextVar[dict[str, Any] | None] = ContextVar("agentops_ctx", default=None)


def bind(**kwargs: Any) -> None:
    current = dict(_ctx.get() or {})
    current.update(kwargs)
    _ctx.set(current)


def get(key: str, default: Any = None) -> Any:
    return (_ctx.get() or {}).get(key, default)


def snapshot() -> dict[str, Any]:
    return dict(_ctx.get() or {})
