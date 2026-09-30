"""工具契约：Pydantic 入参模型 + 风险分级 + 执行策略。"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel


class ToolSpec(BaseModel):
    name: str
    description: str = ""
    risk: Literal["read", "write", "high"] = "read"
    timeout_s: float = 15.0
    retries: int = 1
    idempotent: bool = False

    args_model: Any | None = None  # Pydantic 模型类，用于生成 Function Calling 的 JSON Schema

    @property
    def json_schema(self) -> dict[str, Any]:
        if self.args_model is None:
            return {"type": "object", "properties": {}}
        return self.args_model.model_json_schema()
