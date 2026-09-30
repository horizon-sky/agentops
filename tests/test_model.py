"""模型适配器与 OpenAI SDK 的契约。"""

from types import SimpleNamespace

from langchain_core.messages import HumanMessage
from pydantic import BaseModel

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
    result = await provider.acomplete([HumanMessage(content="test")], response_model=ParsedOut)

    assert seen["response_format"] is ParsedOut
    assert seen["messages"] == [{"role": "user", "content": "test"}]
    assert result.parsed == ParsedOut(value="ok")
