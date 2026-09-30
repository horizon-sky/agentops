"""以 MCP 协议暴露指标查询能力（只读工具，样例数据源）。

运行：
    uv run python -m services.mcp_metrics.server
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from src.tools.builtin import query_metrics

mcp = FastMCP("metrics")


@mcp.tool()
def metrics(service: str = "order-service", window: str = "1h") -> dict[str, object]:
    """查询指定服务在时间窗口内的指标序列（演示数据源）。"""
    return query_metrics({"service": service, "window": window})


if __name__ == "__main__":
    mcp.run()
