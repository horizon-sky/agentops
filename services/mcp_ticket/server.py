"""以 MCP 协议暴露工单创建能力（写操作，需人工确认后执行）。

运行：
    uv run python -m services.mcp_ticket.server
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from src.tools.builtin import create_ticket

mcp = FastMCP("ticket")


@mcp.tool()
def ticket(
    title: str,
    detail: str = "",
    severity: str = "P2",
    idempotency_key: str | None = None,
) -> dict[str, object]:
    """创建运维工单；idempotency_key 相同则视为同一次提交。"""
    return create_ticket(
        {
            "title": title,
            "detail": detail,
            "severity": severity,
            "idempotency_key": idempotency_key,
        }
    )


if __name__ == "__main__":
    mcp.run()
