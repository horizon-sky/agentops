"""M0 冒烟测试：不依赖外部网络，验证配置、Provider 装配与降级路径。"""

from __future__ import annotations

from langchain_core.messages import HumanMessage

from src.agent.model import (
    EchoLLM,
    OpenAIEmbedder,
    OpenAILike,
    build_embedder,
    build_llm,
    build_reranker,
)
from src.config import Settings, get_settings


def test_settings_defaults() -> None:
    settings = get_settings()
    assert isinstance(settings, Settings)
    assert settings.app_env
    assert "http://localhost:3000" in settings.cors_origins_list


def test_offline_fallback_chain() -> None:
    settings = Settings(_env_file=None, llm_api_key="", embedding_api_key="", rerank_enabled=False)
    assert isinstance(build_llm(settings), EchoLLM)
    assert build_embedder(settings) is None
    assert build_reranker(settings) is None


def test_configured_chain_selection() -> None:
    settings = Settings(
        _env_file=None,
        llm_api_key="test-key",
        llm_base_url="https://example.invalid/v1",
        embedding_api_key="test-key",
        embedding_base_url="https://example.invalid/v1",
        rerank_enabled=True,
        rerank_base_url="https://example.invalid/v1",
        rerank_api_key="test-key",
    )
    assert isinstance(build_llm(settings), OpenAILike)
    assert isinstance(build_embedder(settings), OpenAIEmbedder)
    assert build_reranker(settings) is not None


async def test_echo_llm_streams_without_network() -> None:
    settings = Settings(_env_file=None, llm_api_key="")
    llm = build_llm(settings)
    result = await llm.acomplete([HumanMessage(content="订单服务 5xx 排查")])
    assert result.text == "订单服务 5xx 排查"

    chunks = [chunk async for chunk in llm.astream([HumanMessage(content="hi")])]
    assert chunks and "hi" == "".join(chunks)


async def test_disabled_embedder_returns_empty() -> None:
    settings = Settings(_env_file=None, embedding_api_key="")
    assert build_embedder(settings) is None


async def test_noop_reranker_keeps_order() -> None:
    settings = Settings(_env_file=None, rerank_enabled=False)
    assert build_reranker(settings) is None
