from __future__ import annotations


def test_eval_runner_uses_selector_policy_on_windows(monkeypatch) -> None:
    from evals import runner

    policy = object()
    captured: list[object] = []
    monkeypatch.setattr(runner.sys, "platform", "win32")
    monkeypatch.setattr(runner.asyncio, "WindowsSelectorEventLoopPolicy", lambda: policy)
    monkeypatch.setattr(runner.asyncio, "set_event_loop_policy", captured.append)
    monkeypatch.setattr(runner.asyncio, "run", lambda _coro: 0)

    result = runner._run(object())

    assert result == 0
    assert captured == [policy]
