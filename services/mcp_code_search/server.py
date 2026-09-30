"""以 MCP 协议暴露代码检索能力（只读工具）。

运行：
    uv run python -m services.mcp_code_search.server
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from src.tools.builtin import search_code

mcp = FastMCP("code-search")


@mcp.tool()
def code_search(query: str, top_k: int = 5) -> dict[str, object]:
    """在代码仓库中检索关键字或报错信息，返回命中的文件与行号。"""
    return search_code({"query": query, "top_k": top_k})


if __name__ == "__main__":
    mcp.run()
