"""M4 RAG：切分、上下文装配与降级行为。"""

from __future__ import annotations

from src.rag.chunk import chunk_text
from src.rag.context import build_context
from src.rag.hybrid_search import ChunkHit


def test_chunk_text_respects_headings_and_size() -> None:
    text = "# 排查手册\n" + "步骤说明。" * 200 + "\n## 回滚方案\n" + "回滚步骤。" * 100
    chunks = chunk_text(text, size=300, overlap=40)
    assert len(chunks) > 2
    assert chunks[0]["heading"] == "排查手册"
    assert all(len(str(chunk["content"])) <= 340 for chunk in chunks)


def test_chunk_ids_are_stable() -> None:
    first = chunk_text("同一段文本内容" * 10)
    second = chunk_text("同一段文本内容" * 10)
    assert [item["chunk_id"] for item in first] == [item["chunk_id"] for item in second]


def test_build_context_truncates_by_token_budget() -> None:
    hits = [
        ChunkHit(
            chunk_id=f"c{index}",
            title="手册",
            snippet="内容" * 300,
            score=1.0 - index * 0.1,
        )
        for index in range(5)
    ]
    context, citations = build_context(hits, token_budget=200)
    assert len(citations) < len(hits)
    assert citations[0]["chunk_id"] == "c0"
    assert "c0" in context


async def test_hybrid_search_degrades_without_database() -> None:
    from src.config import Settings
    from src.rag.hybrid_search import hybrid_search

    hits = await hybrid_search("订单服务 5xx", top_k=3, settings=Settings(_env_file=None))
    assert hits == []  # 无数据库时返回空，由上层在事件中如实标注


async def test_embed_texts_empty_when_embedding_disabled() -> None:
    from src.config import Settings
    from src.rag.embed import embed_texts

    vectors = await embed_texts(["a", "b"], Settings(_env_file=None))
    assert vectors == [[], []]


async def test_embed_texts_reuses_memory_cache(monkeypatch) -> None:
    from src.agent import model
    from src.config import Settings
    from src.rag import embed

    calls = 0

    class FakeEmbedder:
        model_name = "test-model"

        async def aembed(self, texts):
            nonlocal calls
            calls += 1
            return [[float(len(text))] for text in texts]

    settings = Settings(_env_file=None)
    monkeypatch.setattr(model, "build_embedder", lambda _settings: FakeEmbedder())
    monkeypatch.setattr(embed, "_embedding_caches", {})

    first = await embed.embed_texts(["a", "bb"], settings)
    second = await embed.embed_texts(["a", "bb"], settings)

    assert first == second == [[1.0], [2.0]]
    assert calls == 1


def test_openai_embedder_exposes_model_name() -> None:
    from src.agent.model import OpenAIEmbedder
    from src.config import Settings

    embedder = OpenAIEmbedder(
        Settings(
            _env_file=None,
            embedding_api_key="test-key",
            embedding_base_url="https://example.invalid/v1",
        )
    )
    assert embedder.model_name == "bge-m3"


async def test_rerank_uses_scores_without_mutating_hits(monkeypatch) -> None:
    from src.config import Settings
    from src.rag import rerank

    class FakeReranker:
        async def arank(self, query, docs):
            assert query == "query"
            assert docs == ["first", "second"]
            return [0.2, 0.9]

    monkeypatch.setattr(rerank, "build_reranker", lambda settings: FakeReranker())
    hits = [ChunkHit(chunk_id="a", snippet="first"), ChunkHit(chunk_id="b", snippet="second")]
    ranked = await rerank.rerank_hits("query", hits, 1, Settings(_env_file=None))
    assert [(hit.chunk_id, hit.score, hit.source) for hit in ranked] == [
        ("b", 0.9, "hybrid+rerank")
    ]
    assert hits[1].score == 0.0
