import pytest

from src.agent.context import bind
from src.agent.model import ModelResult
from src.agent.nodes.answer import TicketDraftOut, answer
from src.agent.nodes.review import ReviewOut, review
from src.config import Settings


@pytest.mark.parametrize("operation,expected", [
    ({"ticket_confirmation": True, "tool_results": [{
        "name": "create_ticket", "ok": True, "output": {"ticket_id": "OPS-test"},
    }]}, "工单已创建成功"),
    ({"ticket_confirmation": True, "tool_results": [{
        "name": "create_ticket", "ok": False, "error": "database unavailable",
    }]}, "工单创建未成功"),
    ({"ticket_confirmation": True}, "未收到创建工具的成功结果"),
    ({"ticket_confirmation_error": True}, "没有可匹配"),
    ({"write_denied": True}, "拒绝后未执行写入"),
    ({"intent": "injection"}, "无法执行"),
])
async def test_operation_receipt_is_not_prefixed_with_knowledge_evidence_gap(operation, expected):
    events = []

    async def emit(event):
        events.append(event)

    bind(settings=Settings(_env_file=None), llm=None, emit=emit)
    await answer({
        "run_id": "receipt-test", "query": "确认创建", "plan": {"steps": []},
        "review": {
            "sufficient": False, "next_action": "answer",
            "missing_evidence": ["请求者在创建前对上述内容的明确确认"],
        },
        **operation,
    })
    done = next(event.payload for event in events if event.type == "done")
    streamed = "".join(event.payload["delta"] for event in events if event.type == "token")
    assert expected in done["answer"]
    assert "证据不足" not in done["answer"]
    assert done["answer"] == streamed


@pytest.mark.parametrize("use_model", [False, True])
async def test_knowledge_evidence_gap_is_streamed_and_saved_consistently(use_model):
    class AnswerLLM:
        async def astream(self, messages, tier="strong"):
            yield "连接池承压，"
            yield "根因尚待确认。"

    events = []

    async def emit(event):
        events.append(event)

    bind(settings=Settings(_env_file=None), llm=AnswerLLM() if use_model else None, emit=emit)
    await answer({
        "run_id": "knowledge-test", "intent": "incident", "query": "能确认根因吗？",
        "plan": {"steps": []},
        "review": {
            "sufficient": False, "next_action": "answer", "missing_evidence": ["日志和 Trace"],
        },
    })
    done = next(event.payload for event in events if event.type == "done")
    streamed = "".join(event.payload["delta"] for event in events if event.type == "token")
    assert done["answer"].startswith("证据不足：日志和 Trace。")
    assert done["answer"] == streamed
    if use_model:
        assert "根因尚待确认" in done["answer"]


@pytest.mark.parametrize("operation", [
    {"ticket_confirmation": True}, {"ticket_confirmation_error": True},
    {"write_denied": True}, {"intent": "injection"},
])
async def test_review_does_not_ask_model_to_rejudge_operation_authorization(operation):
    class UnexpectedLLM:
        async def acomplete(self, *args, **kwargs):
            pytest.fail("操作状态不应由知识证据审查重新推断授权")

    async def emit(event):
        pass

    bind(settings=Settings(_env_file=None), llm=UnexpectedLLM(), emit=emit)
    result = await review({
        "run_id": "review-operation", "query": "确认创建", "plan": {"steps": []}, **operation,
    })
    assert result["review"]["next_action"] == "answer"
    assert result["review"]["missing_evidence"] == []
    assert "操作状态" in result["review"]["reason"]


async def test_knowledge_review_still_identifies_evidence_gap():
    class ReviewLLM:
        async def acomplete(self, messages, tier="cheap", response_model=None):
            return ModelResult(parsed=ReviewOut(
                sufficient=False, missing_evidence=["日志和 Trace"],
            ))

    async def emit(event):
        pass

    bind(settings=Settings(_env_file=None), llm=ReviewLLM(), emit=emit)
    result = await review({
        "run_id": "review-knowledge", "query": "能确认根因吗？", "intent": "incident",
        "plan": {"steps": []},
    })
    assert result["review"]["sufficient"] is False
    assert result["review"]["missing_evidence"] == ["日志和 Trace"]


async def test_draft_shows_unknowns_without_unsupported_authorization_warning():
    class DraftLLM:
        async def acomplete(self, messages, tier="strong", response_model=None):
            return ModelResult(parsed=TicketDraftOut(
                title="订单故障跟进", detail="连接池承压，根因尚待确认。", severity="P2",
                unknowns=["故障日志和 Trace"],
            ))

    events = []

    async def emit(event):
        events.append(event)

    bind(settings=Settings(_env_file=None), llm=DraftLLM(), emit=emit)
    result = await answer({
        "run_id": "draft-notice", "intent": "ticket", "query": "生成 P2 草稿，先不要创建",
        "plan": {"steps": []}, "review": {"sufficient": False, "next_action": "answer"},
    })
    assert "证据不足" not in result["answer"]
    assert "### 待确认信息\n- 故障日志和 Trace" in result["answer"]
    assert "目前未创建工单" in result["answer"]
    assert result["ticket_draft"]["detail"] == "连接池承压，根因尚待确认。"
    assert result["answer"] == "".join(
        event.payload["delta"] for event in events if event.type == "token"
    )


@pytest.mark.parametrize("sufficient,next_action,expected", [
    (True, "answer", "[无模型]"),
    (False, "clarify", "请补充：日志和 Trace"),
])
async def test_sufficient_or_clarification_response_has_no_extra_gap_header(
    sufficient, next_action, expected,
):
    events = []

    async def emit(event):
        events.append(event)

    bind(settings=Settings(_env_file=None), llm=None, emit=emit)
    result = await answer({
        "run_id": "notice-control", "query": "故障调查", "plan": {"steps": []},
        "review": {"sufficient": sufficient, "next_action": next_action,
                   "missing_evidence": ["日志和 Trace"]},
    })
    assert result["answer"].startswith(expected)
    assert "证据不足" not in result["answer"]
    assert result["answer"] == "".join(
        event.payload["delta"] for event in events if event.type == "token"
    )
