"""M4 RAG：切分、上下文装配与降级行为。"""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

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


def test_context_uses_unique_citation_uuid_instead_of_shared_content_hash() -> None:
    from src.agent.nodes.answer import _build_context

    hits = [
        ChunkHit(chunk_id="same", citation_id="uuid-a", document_id="a", snippet="Text"),
        ChunkHit(chunk_id="same", citation_id="uuid-b", document_id="b", snippet="Text"),
    ]
    context, citations = build_context(hits)
    assert "[uuid-a]" in context and "[uuid-b]" in context
    assert "[same]" not in context
    assert "[uuid-b]" in _build_context({"citations": citations})


def test_chinese_keyword_terms_do_not_depend_on_embedding() -> None:
    from src.rag.hybrid_search import keyword_terms

    assert "支付" in keyword_terms("支付回调超时怎么处理")
    assert "超时" in keyword_terms("支付回调超时怎么处理")
    assert keyword_terms("5xx order-service") == ["5xx", "order-service"]


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


@pytest.mark.parametrize("failure_stage", ["embedding", "rerank"])
async def test_optional_model_failure_preserves_keyword_results(monkeypatch, failure_stage) -> None:
    from src.agent import model
    from src.config import Settings
    from src.rag import embed, hybrid_search, rerank

    owner_id, citation_id = str(uuid4()), str(uuid4())
    searches = []

    class Connection:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def execute(self, statement, params):
            searches.append((str(statement), params))
            return SimpleNamespace(mappings=lambda: SimpleNamespace(all=lambda: [{
                "citation_id": citation_id, "chunk_id": "hash", "document_id": str(uuid4()),
                "title": "接口500排查", "source_url": "", "heading": "",
                "content": "接口500为服务内部问题", "score": 0.016,
            }]))

    async def unavailable(*args, **kwargs):
        raise TimeoutError("private credentials must never enter diagnostics")

    monkeypatch.setattr(hybrid_search, "get_engine", lambda _: SimpleNamespace(connect=Connection))
    monkeypatch.setattr(model, "build_embedder", lambda _: object() if failure_stage == "embedding"
                        else None)
    monkeypatch.setattr(embed, "embed_texts", unavailable)
    if failure_stage == "rerank":
        monkeypatch.setattr(rerank, "build_reranker", lambda _: SimpleNamespace(arank=unavailable))
    diagnosis = {}
    hits = await hybrid_search.hybrid_search(
        "现在接口500错误了", settings=Settings(_env_file=None), owner_id=owner_id,
        diagnostics=diagnosis,
    )
    assert hits[0].citation_id == citation_id
    assert hits[0].retrieval_method == "keyword"
    assert searches[0][1]["owner_id"] == owner_id
    assert "d.owner_id = CAST(:owner_id AS uuid)" in searches[0][0]
    assert "qv" not in searches[0][1]
    assert diagnosis["degraded"] is True
    assert diagnosis["warnings"] == [f"{failure_stage}_error"]
    assert "private credentials" not in str(diagnosis)
