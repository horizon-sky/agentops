"""向量化：批量调用 Embedder 并缓存；未配置 Embedding 时返回空列表（检索退化为 BM25）。"""

from __future__ import annotations

from typing import Any

BATCH_SIZE = 32
_embedding_caches: dict[str, Any] = {}


def _cache_key(model: str, text: str) -> str:
    return f"emb:{model}:{hash(text)}"


async def embed_texts(texts: list[str], settings: Any) -> list[list[float]]:
    """返回与输入等长同序的向量列表；未配置 Embedding 时每项为空列表。"""
    if not texts:
        return []

    from src.agent.model import build_embedder
    from src.db.cache import build_cache

    embedder = build_embedder(settings)
    if embedder is None:
        return [[] for _ in texts]

    cache_id = getattr(settings, "redis_url", "") or "__memory__"
    cache = _embedding_caches.get(cache_id)
    if cache is None:
        cache = build_cache(settings)
        _embedding_caches[cache_id] = cache
    results: dict[int, list[float]] = {}
    pending: list[tuple[int, str]] = []

    for index, text_value in enumerate(texts):
        cached = await cache.get(_cache_key(embedder.model_name, text_value))
        if cached is not None:
            results[index] = cached
        else:
            pending.append((index, text_value))

    for start in range(0, len(pending), BATCH_SIZE):
        batch = pending[start : start + BATCH_SIZE]
        vectors = await embedder.aembed([item[1] for item in batch])
        for (index, text_value), vector in zip(batch, vectors, strict=False):
            results[index] = vector
            await cache.set(
                _cache_key(embedder.model_name, text_value), vector, ttl_s=86400
            )

    return [results.get(index, []) for index in range(len(texts))]
