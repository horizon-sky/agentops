"""工具注册表：统一执行入口，负责超时、重试、幂等与 MCP 路由。"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable
from time import perf_counter
from typing import Any

from pydantic import ValidationError

from src.agent.context import get as ctx_get
from src.agent.state import ToolResult
from src.config import Settings
from src.db.cache import Cache, build_cache
from src.tools.builtin import (
    CreateTicketArgs,
    DraftReportArgs,
    QueryMetricsArgs,
    SearchCodeArgs,
    create_ticket,
    draft_report,
    query_metrics,
    search_code,
)
from src.tools.spec import ToolSpec

SyncExecutor = Callable[[dict[str, Any]], dict[str, Any]]
AsyncExecutor = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]
Executor = SyncExecutor | AsyncExecutor

_registry: ToolRegistry | None = None


class ToolRegistry:
    def __init__(self, settings: Settings, cache: Cache | None = None) -> None:
        self.settings = settings
        self.cache = cache or build_cache(settings)
        self.specs: dict[str, ToolSpec] = {}
        self.executors: dict[str, Executor] = {}
        self._register_builtin()

    def _register_builtin(self) -> None:
        self.register(
            ToolSpec(
                name="search_code",
                description="在代码仓库中检索关键字或报错信息",
                args_model=SearchCodeArgs,
                risk="read",
                timeout_s=10,
                retries=1,
            ),
            search_code,
        )
        self.register(
            ToolSpec(
                name="query_metrics",
                description="查询指定服务在时间窗口内的指标序列",
                args_model=QueryMetricsArgs,
                risk="read",
                timeout_s=10,
                retries=2,
            ),
            query_metrics,
        )
        self.register(
            ToolSpec(
                name="create_ticket",
                description="创建运维工单（写操作，需人工确认）",
                args_model=CreateTicketArgs,
                risk="high",
                timeout_s=10,
                retries=0,
                idempotent=True,
            ),
            create_ticket,
        )
        self.register(
            ToolSpec(
                name="draft_report",
                description="生成结构化处理报告",
                args_model=DraftReportArgs,
                risk="write",
                timeout_s=10,
                retries=1,
            ),
            draft_report,
        )

    def register(self, spec: ToolSpec, executor: Executor) -> None:
        self.specs[spec.name] = spec
        self.executors[spec.name] = executor

    def specs_payload(self) -> list[dict[str, Any]]:
        """供 Function Calling 使用：OpenAI 兼容的 tools 数组。"""
        return [
            {
                "type": "function",
                "function": {
                    "name": spec.name,
                    "description": spec.description,
                    "parameters": spec.json_schema,
                },
            }
            for spec in self.specs.values()
        ]

    def is_high_risk(self, name: str) -> bool:
        spec = self.specs.get(name)
        return bool(spec and spec.risk in ("write", "high"))

    async def call(
        self, name: str, args: dict[str, Any], *, max_attempts: int | None = None
    ) -> ToolResult:
        spec = self.specs.get(name)
        if spec is None:
            return ToolResult(name=name, args=args, ok=False, error=f"未注册的工具 {name}")

        try:
            args = spec.args_model.model_validate(args).model_dump()
        except ValidationError as exc:
            return ToolResult(
                name=name, args=args, ok=False, error=f"Invalid arguments: {exc}", risk=spec.risk
            )
        if self.is_high_risk(name) and not ctx_get("write_approved", False):
            return ToolResult(
                name=name, args=args, ok=False, error="Write approval required", risk=spec.risk
            )

        # 幂等：key 相同则复用首次结果，避免重复建单
        use_cache = spec.idempotent and name != "create_ticket"
        if use_cache:
            key = (
                f"tool:{ctx_get('user_id', '')}:{name}:"
                f"{args.get('idempotency_key') or args.get('title')}"
            )
            cached = await self.cache.get(key)
            if cached is not None:
                return ToolResult(
                    name=name, args=args, ok=True, output=cached, risk=spec.risk, ms=0
                )

        started = perf_counter()
        output: Any = None
        error: str | None = None
        retries = 0 if self.is_high_risk(name) else spec.retries
        if max_attempts is not None:
            if max_attempts <= 0:
                return ToolResult(
                    name=name,
                    args=args,
                    ok=False,
                    error="Read call budget exhausted",
                    risk=spec.risk,
                )
            retries = min(retries, max_attempts - 1)
        attempts = 0
        for attempt in range(retries + 1):
            attempts += 1
            try:
                executor = self.executors[name]
                if inspect.iscoroutinefunction(executor):
                    output = await asyncio.wait_for(executor(args), timeout=spec.timeout_s)
                else:
                    # A timed-out thread may still finish; never automatically retry writes.
                    output = await asyncio.wait_for(
                        asyncio.to_thread(executor, args), timeout=spec.timeout_s
                    )
                error = None
                break
            except TimeoutError:
                error = f"工具超时（>{spec.timeout_s}s）"
            except Exception as exc:  # noqa: BLE001 - 工具异常需转成结构化结果
                error = f"{type(exc).__name__}: {str(exc)[:160]}"
            if attempt < retries:
                await asyncio.sleep(0.3 * (attempt + 1))

        elapsed = int((perf_counter() - started) * 1000)
        tool_result = ToolResult(
            name=name,
            args=args,
            ok=error is None,
            output=output,
            error=error,
            risk=spec.risk,
            ms=elapsed,
            attempts=attempts,
        )

        if use_cache and tool_result.ok:
            await self.cache.set(
                key,
                output,
                ttl_s=3600,
            )
        return tool_result


def get_registry(settings: Settings | None = None) -> ToolRegistry:
    global _registry
    if _registry is None:
        from src.config import get_settings

        _registry = ToolRegistry(settings or get_settings())
    return _registry
