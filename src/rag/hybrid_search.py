"""混合检索：pgvector 向量检索 + Postgres BM25，RRF 融合，可选 Rerank。

降级策略（如实记录，不伪造召回）：
- Embedding 未配置 → 仅 BM25；
- 数据库不可用 → 返回空并标注 unavailable，由上层在事件中说明。
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import text

from src.config import Settings
from src.db.session import get_engine

RRF_K = 60
CANDIDATES = 20
logger = logging.getLogger("agentops.retrieval")


def _record_degradation(diagnostics: dict[str, Any], stage: str, exc: Exception) -> None:
    diagnostics["degraded"] = True
    diagnostics.setdefault("warnings", []).append(f"{stage}_error")
    diagnostics.setdefault("error_types", {})[stage] = type(exc).__name__
    logger.warning(
        "retrieval_degraded stage=%s error_type=%s status=%s",
        stage, type(exc).__name__, getattr(exc, "status_code", None),
    )


class ChunkHit(BaseModel):
    chunk_id: str
    citation_id: str | None = None
    document_id: str | None = None
    title: str = ""
    snippet: str = ""
    score: float = 0.0
    source: str = "hybrid"
    source_url: str = ""
    heading: str = ""
    retrieval_method: str = ""


def keyword_terms(query: str) -> list[str]:
    """Simple FTS cannot segment Chinese; use literal bigrams as a fallback."""
    terms = re.findall(r"[a-zA-Z0-9_-]+", query)
    for phrase in re.findall(r"[\u4e00-\u9fff]+", query):
        terms.extend(phrase[i : i + 2] for i in range(len(phrase) - 1))
    return list(dict.fromkeys(terms))[:100]


async def hybrid_search(
    query: str,
    top_k: int = 5,
    settings: Settings | None = None,
    owner_id: str | None = None,
    diagnostics: dict[str, Any] | None = None,
) -> list[ChunkHit]:
    diagnostics = diagnostics if diagnostics is not None else {}
    if settings is None:
        from src.config import get_settings

        settings = get_settings()

    engine = get_engine(settings)
    if engine is None:
        return []
    if not owner_id:
        return []
    # Always scope before ranking, including the keyword-only fallback.
    owner_id = str(UUID(owner_id))

    query = query.strip()
    if not query:
        return []

    from src.agent.model import build_embedder

    query_vector: list[float] | None = None
    try:
        if build_embedder(settings) is not None:
            from src.rag.embed import embed_texts

            async with asyncio.timeout(settings.request_timeout_s):
                vectors = await embed_texts([query], settings)
            if not vectors or not vectors[0]:
                raise ValueError("Empty query embedding")
            query_vector = vectors[0]
    except Exception as exc:  # noqa: BLE001 - keyword retrieval remains available
        _record_degradation(diagnostics, "embedding", exc)

    vector_sql = """
        SELECT c.id AS citation_id, c.chunk_id, c.content, c.document_id, d.title,
               d.source AS source_url, c.meta->>'heading' AS heading,
               ROW_NUMBER() OVER (ORDER BY c.embedding <=> CAST(:qv AS vector)) AS rank
        FROM chunks c
        JOIN documents d ON d.id = c.document_id
        WHERE c.embedding IS NOT NULL AND d.owner_id = CAST(:owner_id AS uuid)
        ORDER BY c.embedding <=> CAST(:qv AS vector)
        LIMIT :lim
    """
    keyword_sql = """
        SELECT c.id AS citation_id, c.chunk_id, c.content, c.document_id, d.title,
               d.source AS source_url, c.meta->>'heading' AS heading,
               ROW_NUMBER() OVER (
                   ORDER BY ts_rank_cd(c.tsv, plainto_tsquery('simple', :q)) +
                   (SELECT count(*) FROM unnest(CAST(:terms AS text[])) t(term)
                    WHERE strpos(lower(c.content), lower(t.term)) > 0) DESC, c.id
               ) AS rank
        FROM chunks c
        JOIN documents d ON d.id = c.document_id
        WHERE d.owner_id = CAST(:owner_id AS uuid)
          AND (c.tsv @@ plainto_tsquery('simple', :q) OR
               EXISTS (SELECT 1 FROM unnest(CAST(:terms AS text[])) t(term)
                       WHERE strpos(lower(c.content), lower(t.term)) > 0))
        ORDER BY rank
        LIMIT :lim
    """
    fused_sql = f"""
        WITH vec AS ({vector_sql}), kw AS ({keyword_sql})
        SELECT COALESCE(v.citation_id, k.citation_id) AS citation_id,
               COALESCE(v.source_url, k.source_url) AS source_url,
               COALESCE(v.heading, k.heading) AS heading,
               COALESCE(v.chunk_id, k.chunk_id) AS chunk_id,
               COALESCE(v.content, k.content) AS content,
               COALESCE(v.document_id, k.document_id) AS document_id,
               COALESCE(v.title, k.title) AS title,
               COALESCE(1.0 / ({RRF_K} + v.rank), 0)
               + COALESCE(1.0 / ({RRF_K} + k.rank), 0) AS score
        FROM vec v
        FULL OUTER JOIN kw k ON v.citation_id = k.citation_id
        ORDER BY score DESC
        LIMIT :lim
    """
    keyword_only_sql = f"""
        WITH kw AS ({keyword_sql})
        SELECT citation_id, chunk_id, content, document_id, title, source_url, heading,
               1.0 / ({RRF_K} + rank) AS score
        FROM kw
        ORDER BY score DESC
        LIMIT :lim
    """

    params: dict[str, Any] = {
        "q": query,
        "terms": keyword_terms(query),
        "lim": CANDIDATES,
        "owner_id": owner_id,
    }
    if query_vector is not None:
        params["qv"] = "[" + ",".join(f"{value:.6f}" for value in query_vector) + "]"
        sql = fused_sql
    else:
        sql = keyword_only_sql
    diagnostics["method"] = "hybrid" if query_vector is not None else "keyword"

    async with engine.connect() as conn:
        rows = (await conn.execute(text(sql), params)).mappings().all()

    hits = [
        ChunkHit(
            chunk_id=str(row["chunk_id"]),
            citation_id=str(row["citation_id"]),
            document_id=str(row["document_id"]) if row["document_id"] else None,
            title=str(row["title"] or ""),
            source_url=str(row["source_url"] or ""),
            heading=str(row["heading"] or ""),
            snippet=str(row["content"])[:400],
            score=float(row["score"]),
            source="hybrid" if query_vector is not None else "bm25",
            retrieval_method="hybrid" if query_vector is not None else "keyword",
        )
        for row in rows
    ]

    from src.rag.rerank import rerank_hits

    try:
        async with asyncio.timeout(settings.request_timeout_s):
            return await rerank_hits(query, hits, top_k, settings)
    except Exception as exc:  # noqa: BLE001 - preserve already retrieved evidence
        _record_degradation(diagnostics, "rerank", exc)
        return hits[:top_k]


__all__ = ["ChunkHit", "hybrid_search"]
