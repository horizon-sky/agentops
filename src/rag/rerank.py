"""Rerank：调用外部重排模型；未启用时保持融合排序不变（接口一致）。"""

from __future__ import annotations

from src.agent.model import build_reranker
from src.rag.hybrid_search import ChunkHit


async def rerank_hits(
    query: str,
    hits: list[ChunkHit],
    top_k: int,
    settings,
) -> list[ChunkHit]:
    if not hits:
        return []
    reranker = build_reranker(settings)
    if reranker is None:
        return hits[:top_k]

    docs = [hit.snippet for hit in hits]
    scores = await reranker.arank(query, docs)
    reranked: list[ChunkHit] = []
    if len(scores) != len(hits):
        return hits[:top_k]
    for index in sorted(range(len(hits)), key=lambda item: scores[item], reverse=True)[:top_k]:
        hit = hits[index].model_copy(
            update={
                "score": float(scores[index]),
                "source": f"{hits[index].source}+rerank",
            }
        )
        reranked.append(hit)
    return reranked or hits[:top_k]
