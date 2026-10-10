"""Agent 状态定义：LangGraph 节点间传递的唯一数据结构。"""

from __future__ import annotations

from typing import Any, TypedDict

from pydantic import BaseModel, Field


class Citation(BaseModel):
    chunk_id: str
    document_id: str | None = None
    title: str = ""
    snippet: str = ""
    score: float = 0.0


class ToolCall(BaseModel):
    name: str
    args: dict[str, Any] = Field(default_factory=dict)


class ToolResult(BaseModel):
    name: str
    step_id: str = ""
    args: dict[str, Any] = Field(default_factory=dict)
    ok: bool = True
    output: Any | None = None
    error: str | None = None
    ms: int = 0
    risk: str = "read"
    attempts: int = 0


class HitlRequest(BaseModel):
    """HITL 挂起请求：写类工具必须经人工确认后才能执行。"""

    tool: str
    args: dict[str, Any] = Field(default_factory=dict)
    reason: str = ""


class AgentState(TypedDict, total=False):
    run_id: str
    session_id: str
    user_id: str
    query: str
    intent: str
    confident: bool
    plan: dict[str, Any]
    citations: list[dict[str, Any]]
    retrieval: dict[str, Any]
    pending_calls: list[dict[str, Any]]
    tool_results: list[dict[str, Any]]
    hitl: dict[str, Any] | None
    draft: str
    answer: str
    sufficient: bool
    retry: int
    error_stage: str
    operations: dict[str, dict[str, Any]]
    tools_pending: bool
    active_step_ids: list[str]
    flags: dict[str, bool | str]
    review: dict[str, Any]
    fingerprints: list[str]
    read_calls: int
    execution_ms: int
    retry_query: str
    stop_reason: str
