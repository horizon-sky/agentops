"""REST 请求 / 响应契约。"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class CreateSessionIn(BaseModel):
    title: str = "新会话"


class SessionOut(BaseModel):
    id: UUID
    title: str
    created_at: datetime | None = None


class CreateRunIn(BaseModel):
    session_id: UUID
    query: str = Field(min_length=1, max_length=4000)
    tier: str = "strong"


class RunOut(BaseModel):
    id: UUID
    session_id: UUID
    status: str
    model_version: str = ""
    prompt_version: str = ""


class ResumeIn(BaseModel):
    ok: bool
    args: dict[str, Any] | None = None
    comment: str | None = None


class OkOut(BaseModel):
    ok: bool
    detail: str | None = None


class IngestIn(BaseModel):
    title: str
    source: str = ""
    content: str = ""
    version: str = "v1"


class IngestOut(BaseModel):
    document_id: UUID
    chunks: int
    embedded: int = 0


class TraceNode(BaseModel):
    id: UUID
    stage: str
    name: str
    status: str
    ms: int = 0
    tokens: int = 0
    cost: float = 0.0
    inputs: dict[str, Any] = Field(default_factory=dict)
    outputs: dict[str, Any] = Field(default_factory=dict)
    children: list[TraceNode] = Field(default_factory=list)


class EvalReportOut(BaseModel):
    generated_at: datetime | None = None
    metrics: dict[str, Any] = Field(default_factory=dict)
    report_path: str = ""


class HealthOut(BaseModel):
    status: str
    env: str
    db: dict[str, Any]
    cache: str
    llm: str
    embedding: str
    rerank: str
    prompt_version: str
