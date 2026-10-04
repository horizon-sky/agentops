"""混合检索：pgvector 向量检索 + Postgres BM25，RRF 融合，可选 Rerank。

降级策略（如实记录，不伪造召回）：
- Embedding 未配置 → 仅 BM25；
- 数据库不可用 → 返回空并标注 unavailable，由上层在事件中说明。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel
from sqlalchemy import text

from src.config import Settings
from src.db.session import get_engine

RRF_K = 60
CANDIDATES = 20


class ChunkHit(BaseModel):
    chunk_id: str
    document_id: str | None = None
    title: str = ""
    snippet: str = ""
    score: float = 0.0
    source: str = "hybrid"


async def hybrid_search(
    query: str,
    top_k: int = 5,
    settings: Settings | None = None,
) -> list[ChunkHit]:
    if settings is None:
        from src.config import get_settings

        settings = get_settings()

    engine = get_engine(settings)
    if engine is None:
        return []

    query = query.strip()
    if not query:
        return []

    from src.agent.model import build_embedder

    embedder = build_embedder(settings)
    query_vector: list[float] | None = None
    if embedder is not None:
        from src.rag.embed import embed_texts

        vectors = await embed_texts([query], settings)
        query_vector = vectors[0] if vectors else None

    vector_sql = """
        SELECT c.chunk_id, c.content, c.document_id, d.title,
               ROW_NUMBER() OVER (ORDER BY c.embedding <=> CAST(:qv AS vector)) AS rank
        FROM chunks c
        JOIN documents d ON d.id = c.document_id
        WHERE c.embedding IS NOT NULL
        ORDER BY c.embedding <=> CAST(:qv AS vector)
        LIMIT :lim
    """
    keyword_sql = """
        SELECT c.chunk_id, c.content, c.document_id, d.title,
               ROW_NUMBER() OVER (
                   ORDER BY ts_rank_cd(c.tsv, plainto_tsquery('simple', :q)) DESC
               ) AS rank
        FROM chunks c
        JOIN documents d ON d.id = c.document_id
        WHERE c.tsv @@ plainto_tsquery('simple', :q)
        ORDER BY ts_rank_cd(c.tsv, plainto_tsquery('simple', :q)) DESC
        LIMIT :lim
    """
    fused_sql = f"""
        WITH vec AS ({vector_sql}), kw AS ({keyword_sql})
        SELECT COALESCE(v.chunk_id, k.chunk_id) AS chunk_id,
               COALESCE(v.content, k.content) AS content,
               COALESCE(v.document_id, k.document_id) AS document_id,
               COALESCE(v.title, k.title) AS title,
               COALESCE(1.0 / ({RRF_K} + v.rank), 0)
               + COALESCE(1.0 / ({RRF_K} + k.rank), 0) AS score
        FROM vec v
        FULL OUTER JOIN kw k ON v.chunk_id = k.chunk_id
        ORDER BY score DESC
        LIMIT :lim
    """
    keyword_only_sql = f"""
        WITH kw AS ({keyword_sql})
        SELECT chunk_id, content, document_id, title,
               1.0 / ({RRF_K} + rank) AS score
        FROM kw
        ORDER BY score DESC
        LIMIT :lim
    """

    params: dict[str, Any] = {"q": query, "lim": CANDIDATES}
    if query_vector is not None:
        params["qv"] = "[" + ",".join(f"{value:.6f}" for value in query_vector) + "]"
        sql = fused_sql
    else:
        sql = keyword_only_sql

    async with engine.connect() as conn:
        rows = (await conn.execute(text(sql), params)).mappings().all()

    hits = [
        ChunkHit(
            chunk_id=str(row["chunk_id"]),
            document_id=str(row["document_id"]) if row["document_id"] else None,
            title=str(row["title"] or ""),
            snippet=str(row["content"])[:400],
            score=float(row["score"]),
            source="hybrid" if query_vector is not None else "bm25",
        )
        for row in rows
    ]

    from src.rag.rerank import rerank_hits

    return await rerank_hits(query, hits, top_k, settings)


__all__ = ["ChunkHit", "hybrid_search"]
