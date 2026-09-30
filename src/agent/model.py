"""模型接入抽象层（业务代码）。

统一封装三类模型能力，调用方只依赖以下 Protocol，不直接耦合任何厂商 SDK：

- LLMProvider：对话 / 结构化输出 / 流式生成（acomplete + astream）
- Embedder：文本向量化（aembed）
- Reranker：候选重排（arank）

离线兜底策略：未配置 API Key 时，LLM 返回 EchoLLM（规则 + 回显），Embedder/Reranker 返回 None，
上层据此降级（RAG 退化为 BM25，分类退化为关键词规则），保证链路在无密钥环境也能跑通。
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

# 结构化输出用的 Pydantic 模型来自节点内部定义，这里只做类型标注
StructuredModel = Any


@dataclass
class ModelResult:
    """一次 `acomplete` 的统一返回。"""

    text: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    usage: dict[str, Any] = field(default_factory=dict)
    parsed: Any = None  # 传入 response_model 时由 SDK 解析出的对象


@runtime_checkable
class LLMProvider(Protocol):
    async def acomplete(
        self,
        messages: Sequence[Any],
        tier: str = "strong",
        response_model: StructuredModel | None = None,
    ) -> ModelResult: ...

    async def astream(
        self,
        messages: Sequence[Any],
        tier: str = "strong",
    ) -> AsyncIterator[str]: ...


@runtime_checkable
class Embedder(Protocol):
    async def aembed(self, texts: Sequence[str]) -> list[list[float]]: ...


@runtime_checkable
class Reranker(Protocol):
    async def arank(self, query: str, docs: Sequence[str]) -> list[float]: ...


# --------------------------------------------------------------------------- #
# 离线兜底实现
# --------------------------------------------------------------------------- #
class EchoLLM:
    """无 API Key 时的兜底：保证链路可跑通，但不产生真实推理。

    - 结构化请求（传入 response_model）：返回 parsed=None，由调用方走规则兜底；
    - 普通请求：把最后一条 user 消息原样回显，供前端验证 SSE 与事件流。
    """

    def __init__(self, settings: Any) -> None:
        self.settings = settings

    async def acomplete(
        self,
        messages: Sequence[Any],
        tier: str = "strong",
        response_model: StructuredModel | None = None,
    ) -> ModelResult:
        if response_model is not None:
            return ModelResult(text="", parsed=None)
        text = _last_user_text(messages)
        return ModelResult(text=text, usage={"prompt_tokens": 0, "completion_tokens": 0})

    async def astream(
        self,
        messages: Sequence[Any],
        tier: str = "strong",
    ) -> AsyncIterator[str]:
        text = _last_user_text(messages)
        for token in [text[i : i + 12] for i in range(0, len(text), 12)] or [text]:
            yield token


def _last_user_text(messages: Sequence[Any]) -> str:
    for message in reversed(list(messages)):
        content = getattr(message, "content", None)
        if content and getattr(message, "type", "human") in ("human", "user"):
            return str(content)
    return ""


# --------------------------------------------------------------------------- #
# OpenAI 兼容实现
# --------------------------------------------------------------------------- #
class OpenAILike:
    """任意 OpenAI 兼容端点（DeepSeek / Qwen / OpenAI 等）。

    通过 settings.llm_base_url / llm_api_key / llm_model_cheap / llm_model_strong 配置；
    tier 决定使用强模型（规划/生成）还是廉价模型（分类/改写）。
    """

    def __init__(self, settings: Any) -> None:
        self.settings = settings
        from openai import AsyncOpenAI

        self._client = AsyncOpenAI(
            base_url=settings.llm_base_url or None,
            api_key=settings.llm_api_key or "EMPTY",
        )
        self._cheap = settings.llm_model_cheap or settings.llm_model
        self._strong = settings.llm_model_strong or settings.llm_model

    def _model(self, tier: str) -> str:
        return self._strong if tier == "strong" else self._cheap

    def _messages(self, messages: Sequence[Any]) -> list[dict[str, str]]:
        out: list[dict[str, str]] = []
        for message in messages:
            role = getattr(message, "type", "user")
            role = {"ai": "assistant", "human": "user"}.get(role, role)
            out.append({"role": role, "content": str(getattr(message, "content", ""))})
        return out

    async def acomplete(
        self,
        messages: Sequence[Any],
        tier: str = "strong",
        response_model: StructuredModel | None = None,
    ) -> ModelResult:
        payload: dict[str, Any] = {
            "model": self._model(tier),
            "messages": self._messages(messages),
        }
        if response_model is not None:
            completion = await self._client.beta.chat.completions.parse(
                **payload, response_format=response_model
            )
            parsed = completion.choices[0].message.parsed
            return ModelResult(text="", parsed=parsed, usage=_usage(completion))

        completion = await self._client.chat.completions.create(**payload)
        choice = completion.choices[0]
        text = choice.message.content or ""
        return ModelResult(text=text, usage=_usage(completion))

    async def astream(
        self,
        messages: Sequence[Any],
        tier: str = "strong",
    ) -> AsyncIterator[str]:
        stream = await self._client.chat.completions.create(
            model=self._model(tier),
            messages=self._messages(messages),
            stream=True,
        )
        async for chunk in stream:
            delta = chunk.choices[0].delta.content if chunk.choices else None
            if delta:
                yield delta


def _usage(completion: Any) -> dict[str, Any]:
    usage = getattr(completion, "usage", None)
    if usage is None:
        return {}
    return {
        "prompt_tokens": getattr(usage, "prompt_tokens", 0),
        "completion_tokens": getattr(usage, "completion_tokens", 0),
    }


class OpenAIEmbedder:
    """OpenAI 兼容 Embedding 端点。"""

    def __init__(self, settings: Any) -> None:
        self.settings = settings
        from openai import AsyncOpenAI

        self._client = AsyncOpenAI(
            base_url=settings.embedding_base_url or None,
            api_key=settings.embedding_api_key or "EMPTY",
        )
        self._model = settings.embedding_model
        self.dims = settings.embedding_dim

    async def aembed(self, texts: Sequence[str]) -> list[list[float]]:
        resp = await self._client.embeddings.create(model=self._model, input=list(texts))
        return [item.embedding for item in resp.data]


class OpenAIReranker:
    """OpenAI 兼容 Rerank 端点（返回每条 doc 的相关性分数）。"""

    def __init__(self, settings: Any) -> None:
        self.settings = settings
        from openai import AsyncOpenAI

        self._client = AsyncOpenAI(
            base_url=settings.rerank_base_url or None,
            api_key=settings.rerank_api_key or "EMPTY",
        )
        self._model = settings.rerank_model

    async def arank(self, query: str, docs: Sequence[str]) -> list[float]:
        resp = await self._client.embeddings.create(
            model=self._model, input=[query, *docs]
        )
        # 退化实现：用 query 与 doc 的向量点积近似相关性（仅当端点不支持 rerank 时）。
        # 真实 rerank 端点应解析 `[score, index]` 结构。
        q_vec = resp.data[0].embedding
        scores: list[float] = []
        for item in resp.data[1:]:
            vec = item.embedding
            dot = sum(a * b for a, b in zip(q_vec, vec, strict=False)) / (len(q_vec) or 1)
            scores.append(float(dot))
        return scores


# --------------------------------------------------------------------------- #
# 工厂函数
# --------------------------------------------------------------------------- #
def build_llm(settings: Any) -> LLMProvider:
    if settings.llm_api_key:
        return OpenAILike(settings)
    return EchoLLM(settings)


def build_embedder(settings: Any) -> Embedder | None:
    if settings.embedding_api_key and settings.embedding_model:
        return OpenAIEmbedder(settings)
    return None


def build_reranker(settings: Any) -> Reranker | None:
    if settings.rerank_enabled and settings.rerank_api_key and settings.rerank_model:
        return OpenAIReranker(settings)
    return None


__all__ = [
    "ModelResult",
    "LLMProvider",
    "Embedder",
    "Reranker",
    "EchoLLM",
    "OpenAILike",
    "OpenAIEmbedder",
    "OpenAIReranker",
    "build_llm",
    "build_embedder",
    "build_reranker",
]
