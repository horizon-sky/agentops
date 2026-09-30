"""Query Rewrite：把多轮指代补全成可检索的独立问句。"""

from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage

from src.agent.model import LLMProvider

SYSTEM = "把用户问题改写为适合检索的独立问句，补全指代但不臆造信息，只输出改写结果。"


async def rewrite_query(query: str, history: list[str] | None, llm: LLMProvider) -> str:
    if not history:
        return query
    context = "\n".join(history[-4:])
    result = await llm.acomplete(
        [
            SystemMessage(content=SYSTEM),
            HumanMessage(content=f"历史：{context}\n当前问题：{query}"),
        ],
        tier="cheap",
    )
    return (result.text or query).strip() or query
