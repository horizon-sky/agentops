"""上下文装配：按 Token 预算裁剪，并生成可溯源引用。"""

from __future__ import annotations

from src.rag.hybrid_search import ChunkHit

DEFAULT_BUDGET = 1500


def build_context(
    hits: list[ChunkHit], token_budget: int = DEFAULT_BUDGET
) -> tuple[str, list[dict]]:
    """返回 (上下文文本, 引用列表)。超出预算时按分数从高到低截取。"""
    used = 0
    lines: list[str] = []
    citations: list[dict] = []
    for hit in hits:
        cost = max(1, len(hit.snippet) // 3)
        if used + cost > token_budget:
            break
        used += cost
        lines.append(f"[{hit.citation_id or hit.chunk_id}] {hit.snippet}")
        citations.append(hit.model_dump())
    return "\n\n".join(lines), citations
