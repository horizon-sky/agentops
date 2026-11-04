from __future__ import annotations

from apps.api.src.schemas.events import AgentEvent
from evals import runner
from src.config import Settings


async def test_eval_runner_leaves_write_approval_pending(monkeypatch):
    class WaitingRunner:
        def __init__(self):
            self.resume_calls = 0
            self.pending = True

        async def run(self, run_id, query, collector, **kwargs):
            await collector(AgentEvent(
                type="hitl_request", run_id=run_id,
                payload={
                    "approval_id": f"{run_id}:ticket",
                    "tool": "create_ticket",
                    "args": {"title": "待确认"},
                },
            ))

        async def awaiting_approval(self, _run_id):
            return self.pending

        async def resume(self, *_args, **_kwargs):
            self.resume_calls += 1
            self.pending = False

    statuses = []
    fake_runner = WaitingRunner()

    async def create_run(*_args, **_kwargs):
        return None

    async def finish_run(_run_id, _settings, status):
        statuses.append(status)

    monkeypatch.setattr(runner, "_create_eval_run", create_run)
    monkeypatch.setattr(runner, "_finish_eval_run", finish_run)
    result = await runner.run_case(
        {
            "id": "ticket-awaiting-confirmation",
            "query": "拟一张工单，先展示，等我确认后再创建",
            "expect_intent": None,
            "expect_tools": [],
            "forbidden_tools": [],
            "expect_hitl": True,
        },
        fake_runner,
        Settings(_env_file=None),
    )

    assert fake_runner.resume_calls == 0
    assert result["approval_pending"] is True
    assert result["approval_timing_status"] == "awaiting_human_approval"
    assert statuses == ["awaiting_approval"]
    assert result["passed"] is True
