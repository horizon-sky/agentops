"""工具注册表：统一执行入口，负责超时、重试、幂等与 MCP 路由。"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from time import perf_counter
from typing import Any

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

    async def call(self, name: str, args: dict[str, Any]) -> ToolResult:
        spec = self.specs.get(name)
        if spec is None:
            return ToolResult(name=name, args=args, ok=False, error=f"未注册的工具 {name}")

        # 幂等：key 相同则复用首次结果，避免重复建单
        if spec.idempotent:
            key = f"tool:{name}:{args.get('idempotency_key') or args.get('title')}"
            cached = await self.cache.get(key)
            if cached is not None:
                return ToolResult(
                    name=name, args=args, ok=True, output=cached, risk=spec.risk, ms=0
                )

        started = perf_counter()
        output: Any = None
        error: str | None = None
        for attempt in range(spec.retries + 1):
            try:
                maybe = self.executors[name](args)
                if asyncio.iscoroutine(maybe):
                    output = await asyncio.wait_for(maybe, timeout=spec.timeout_s)
                else:
                    output = await asyncio.wait_for(
                        asyncio.to_thread(lambda value=maybe: value), timeout=spec.timeout_s
                    )
                error = None
                break
            except TimeoutError:
                error = f"工具超时（>{spec.timeout_s}s）"
            except Exception as exc:  # noqa: BLE001 - 工具异常需转成结构化结果
                error = f"{type(exc).__name__}: {str(exc)[:160]}"
            if attempt < spec.retries:
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
        )

        if spec.idempotent and tool_result.ok:
            await self.cache.set(
                f"tool:{name}:{args.get('idempotency_key') or args.get('title')}",
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
