"""模型适配器与 OpenAI SDK 的契约。"""

from types import SimpleNamespace

import httpx
import pytest
from langchain_core.messages import HumanMessage
from openai import APIStatusError
from pydantic import BaseModel

from src.agent.context import bind
from src.agent.model import OpenAILike
from src.config import Settings


class ParsedOut(BaseModel):
    value: str


async def test_structured_completion_uses_response_format() -> None:
    provider = OpenAILike(Settings(_env_file=None, llm_api_key="test"))
    seen = {}

    async def parse(**kwargs):
        seen.update(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(parsed=ParsedOut(value="ok")))],
            usage=None,
        )

    provider._client = SimpleNamespace(
        beta=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(parse=parse)))
    )
    provider._client.with_options = lambda **kwargs: provider._client
    result = await provider.acomplete([HumanMessage(content="test")], response_model=ParsedOut)

    assert seen["response_format"] is ParsedOut
    assert seen["messages"] == [{"role": "user", "content": "test"}]
    assert result.parsed == ParsedOut(value="ok")


@pytest.mark.parametrize("status", [400, 500])
async def test_unsupported_schema_uses_validated_json_and_remembers_model(status) -> None:
    provider = OpenAILike(Settings(_env_file=None, llm_api_key="test"))
    schema_calls, json_calls = [], []

    async def parse(**kwargs):
        schema_calls.append(kwargs)
        raise APIStatusError(
            "unsupported format",
            response=httpx.Response(status, request=httpx.Request("POST", "https://test.invalid")),
            body={"error": {"message": "response_format json_schema is not supported"}},
        )

    async def create(**kwargs):
        json_calls.append(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content='{"value":"ok"}'))],
            usage=None,
        )

    provider._client = SimpleNamespace(
        beta=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(parse=parse))),
        chat=SimpleNamespace(completions=SimpleNamespace(create=create)),
    )
    provider._client.with_options = lambda **kwargs: provider._client
    for _ in range(2):
        result = await provider.acomplete([HumanMessage(content="test")], response_model=ParsedOut)
        assert result.parsed == ParsedOut(value="ok")
    assert len(schema_calls) == 1
    assert len(json_calls) == 2
    assert json_calls[0]["response_format"] == {"type": "json_object"}
    assert "value" in json_calls[0]["messages"][0]["content"]


@pytest.mark.parametrize("failure", ["invalid_json", "unrelated_server_error"])
async def test_structured_fallback_does_not_hide_other_failures(failure) -> None:
    provider = OpenAILike(Settings(_env_file=None, llm_api_key="test"))
    calls = []

    async def parse(**kwargs):
        raise APIStatusError(
            "error",
            response=httpx.Response(500, request=httpx.Request("POST", "https://test.invalid")),
            body={"error": {"message": (
                "json_schema unsupported" if failure == "invalid_json" else "server overloaded"
            )}},
        )

    async def create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content='{"unrelated":true}'))],
            usage=None,
        )

    provider._client = SimpleNamespace(
        beta=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(parse=parse))),
        chat=SimpleNamespace(completions=SimpleNamespace(create=create)),
    )
    provider._client.with_options = lambda **kwargs: provider._client
    from pydantic import ValidationError

    with pytest.raises(ValidationError if failure == "invalid_json" else APIStatusError):
        await provider.acomplete([HumanMessage(content="test")], response_model=ParsedOut)
    assert len(calls) == (1 if failure == "invalid_json" else 0)


async def test_stream_requests_usage_and_reports_final_usage() -> None:
    provider = OpenAILike(Settings(_env_file=None, llm_api_key="test"))
    seen = {}
    recorded = []

    async def create(**kwargs):
        seen.update(kwargs)

        async def chunks():
            yield SimpleNamespace(
                choices=[SimpleNamespace(delta=SimpleNamespace(content="hello"))],
                usage=None,
            )
            yield SimpleNamespace(choices=[], usage=SimpleNamespace(
                prompt_tokens=12, completion_tokens=3, total_tokens=15
            ))

        return chunks()

    async def callback(call):
        recorded.append(call)

    provider._client = SimpleNamespace(chat=SimpleNamespace(
        completions=SimpleNamespace(create=create)
    ))
    bind(model_usage_callback=callback, agent_node="answer")
    try:
        chunks = [chunk async for chunk in provider.astream([HumanMessage(content="test")])]
    finally:
        bind(model_usage_callback=None, agent_node=None)

    assert chunks == ["hello"]
    assert seen["stream"] is True
    assert seen["stream_options"] == {"include_usage": True}
    assert recorded[0]["usage"] == {
        "prompt_tokens": 12, "completion_tokens": 3, "total_tokens": 15
    }
    assert recorded[0]["usage_status"] == "available"
    assert recorded[0]["agent_node"] == "answer"


async def test_stream_without_usage_reports_missing_usage() -> None:
    provider = OpenAILike(Settings(_env_file=None, llm_api_key="test"))
    recorded = []

    async def create(**_kwargs):
        async def chunks():
            yield SimpleNamespace(
                choices=[SimpleNamespace(delta=SimpleNamespace(content="hello"))],
                usage=None,
            )

        return chunks()

    async def callback(call):
        recorded.append(call)

    provider._client = SimpleNamespace(chat=SimpleNamespace(
        completions=SimpleNamespace(create=create)
    ))
    bind(model_usage_callback=callback)
    try:
        chunks = [chunk async for chunk in provider.astream([HumanMessage(content="test")])]
        assert chunks == ["hello"]
    finally:
        bind(model_usage_callback=None)

    assert recorded[0]["usage"] is None
    assert recorded[0]["usage_status"] == "unavailable"


async def test_interrupted_stream_records_missing_usage_status() -> None:
    provider = OpenAILike(Settings(_env_file=None, llm_api_key="test"))
    recorded = []

    async def create(**_kwargs):
        async def chunks():
            yield SimpleNamespace(
                choices=[SimpleNamespace(delta=SimpleNamespace(content="hello"))],
                usage=None,
            )
            yield SimpleNamespace(choices=[], usage=SimpleNamespace(
                prompt_tokens=12, completion_tokens=3, total_tokens=15
            ))

        return chunks()

    async def callback(call):
        recorded.append(call)

    provider._client = SimpleNamespace(chat=SimpleNamespace(
        completions=SimpleNamespace(create=create)
    ))
    bind(model_usage_callback=callback)
    try:
        stream = provider.astream([HumanMessage(content="test")])
        assert await anext(stream) == "hello"
        await stream.aclose()
    finally:
        bind(model_usage_callback=None)

    assert recorded[0]["usage"] is None
    assert recorded[0]["usage_status"] == "unavailable"
    assert recorded[0]["call_status"] == "interrupted"


async def test_non_streaming_completion_reports_usage() -> None:
    provider = OpenAILike(Settings(_env_file=None, llm_api_key="test"))
    recorded = []

    async def create(**_kwargs):
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))],
            usage=SimpleNamespace(prompt_tokens=5, completion_tokens=2, total_tokens=7),
        )

    async def callback(call):
        recorded.append(call)

    provider._client = SimpleNamespace(chat=SimpleNamespace(
        completions=SimpleNamespace(create=create)
    ))
    bind(model_usage_callback=callback)
    try:
        result = await provider.acomplete([HumanMessage(content="test")])
    finally:
        bind(model_usage_callback=None)

    assert result.usage["total_tokens"] == 7
    assert recorded[0]["usage_status"] == "available"
    assert recorded[0]["mode"] == "non_streaming"
