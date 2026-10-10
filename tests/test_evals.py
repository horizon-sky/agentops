from __future__ import annotations


def test_eval_runner_uses_selector_policy_on_windows(monkeypatch) -> None:
    from evals import runner

    policy = object()
    captured: list[object] = []
    monkeypatch.setattr(runner.sys, "platform", "win32")
    monkeypatch.setattr(
        runner.asyncio,
        "WindowsSelectorEventLoopPolicy",
        lambda: policy,
        raising=False,
    )
    monkeypatch.setattr(runner.asyncio, "set_event_loop_policy", captured.append)
    monkeypatch.setattr(runner.asyncio, "run", lambda _coro: 0)

    result = runner._run(object())

    assert result == 0
    assert captured == [policy]


def test_judge_rejects_extra_tools_bad_order_and_excess_approvals():
    from evals.judges import judge

    case = {
        "expect_tools": ["search_code"], "forbidden_tools": ["create_ticket"],
        "max_approvals": 1, "max_retries": 2,
        "event_order": ["retrieve", "hitl_request", "done"],
    }
    trace = {
        "tools": ["search_code", "create_ticket"], "approval_count": 2, "retry_count": 3,
        "events": ["hitl_request", "retrieve", "done"],
    }
    result = judge(case, trace)
    assert not result["passed"]
    assert not result["stages"]["plan"]
    assert not result["stages"]["tools"]
