from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from src.config import Settings


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


async def test_eval_collector_captures_first_answer_retrieval_and_tool_evidence():
    from apps.api.src.schemas.events import AgentEvent
    from evals.runner import Collector

    started_at = datetime.now(UTC)
    collector = Collector(started_at)
    await collector(AgentEvent(
        type="retrieve", run_id="run-1", ts=started_at + timedelta(milliseconds=40),
        payload={
            "hits": 1,
            "retrieval": {"mode": "graph", "status": "hit", "method": "hybrid"},
            "citations": [{"citation_id": "cite-1", "chunk_id": "chunk-1", "score": 0.5}],
        },
    ))
    await collector(AgentEvent(
        type="token", run_id="run-1", ts=started_at + timedelta(milliseconds=75),
        payload={"delta": "已查到依据"},
    ))
    await collector(AgentEvent(
        type="tool_result", run_id="run-1", payload={
            "name": "query_metrics", "step_id": "metrics", "args": {"window": "1h"},
            "ok": True, "output": {"note": "sample"}, "ms": 12, "attempts": 1,
        },
    ))

    assert collector.first_answer_ms == 75
    assert collector.retrieval == {"mode": "graph", "status": "hit", "method": "hybrid"}
    assert collector.citation_refs == [{
        "citation_id": "cite-1", "chunk_id": "chunk-1", "score": 0.5,
    }]
    assert collector.tools == ["query_metrics"]
    assert collector.tool_events[0]["args"] == {"window": "1h"}
    assert collector.tool_events[0]["output"] == '{"note": "sample"}'


async def test_eval_collector_ignores_empty_text_and_bounds_tool_output():
    from apps.api.src.schemas.events import AgentEvent
    from evals.runner import Collector

    started_at = datetime.now(UTC)
    collector = Collector(started_at)
    await collector(AgentEvent(
        type="token", run_id="run-1", ts=started_at + timedelta(milliseconds=10),
        payload={"delta": "  \n"},
    ))
    await collector(AgentEvent(
        type="token", run_id="run-1", ts=started_at + timedelta(milliseconds=20),
        payload={"delta": "有内容"},
    ))
    await collector(AgentEvent(
        type="tool_result", run_id="run-1", payload={
            "name": "search_code", "ok": True, "output": {"result": "x" * 3000},
        },
    ))

    assert collector.first_answer_ms == 20
    assert len(collector.tool_events[0]["output"]) == 2000
    assert collector.tool_events[0]["output_truncated"] is True


def test_agentops_seed_materials_load_as_four_independent_documents():
    from scripts.evaluate_isolated import load_agentops_materials

    dataset_path = Path("evals/agentops_eval_v1.json")
    materials = load_agentops_materials(dataset_path)

    assert len(materials) == 4
    assert [item["source"] for item in materials] == [
        "eval-fixture://demoshop/service-map-v1",
        "eval-fixture://demoshop/order-runbook-v1",
        "eval-fixture://demoshop/metrics-2026-10-20",
        "eval-fixture://demoshop/ticket-policy-v1",
    ]
    assert "310 ms" in materials[2]["content"]
    assert "335 ms" in materials[2]["content"]
    assert "建议测试问题" not in materials[3]["content"]


def test_agentops_case_normalization_enforces_expected_tool_boundary():
    from evals.runner import _normalize_case

    case02 = _normalize_case({
        "expected_intent": "incident",
        "expected_tools": [],
        "optional_tools": ["query_metrics"],
        "forbidden_tools": ["create_ticket"],
        "citation_required": True,
    }, "agentops_eval_v1")
    case03 = _normalize_case({
        "expected_intent": "incident",
        "expected_tools": [],
        "optional_tools": [],
        "forbidden_tools": ["create_ticket"],
        "citation_required": True,
    }, "agentops_eval_v1")

    assert "query_metrics" not in case02["forbidden_tools"]
    assert "query_metrics" in case03["forbidden_tools"]
    assert case02["require_citation"] is True


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


def test_aggregate_does_not_present_unmeasured_tokens_and_cost_as_zero():
    from evals.metrics import aggregate

    metrics = aggregate([{
        "passed": False, "latency_ms": 100, "tool_accuracy": 0.5,
        "tokens": 0, "cost_usd": 0.0, "failure_stage": "retrieve",
    }])
    assert metrics["avg_tokens"] is None
    assert metrics["cost_per_task"] is None
    assert metrics["recall_at_5"] is None
    assert metrics["task_success_rate"] == 0.0


@pytest.mark.parametrize("settings_overrides,retrieval", [
    ({}, "unavailable"),
    ({"database_url": "postgresql://unused"}, "bm25"),
    ({"database_url": "postgresql://unused", "embedding_api_key": "unused",
      "embedding_model": ""}, "bm25"),
    ({"database_url": "postgresql://unused", "embedding_api_key": "unused",
      "embedding_model": "test-embedding"}, "hybrid"),
])
async def test_runner_writes_completed_provenance_only_after_all_selected_cases(
    tmp_path, monkeypatch, settings_overrides, retrieval,
):
    from evals import runner

    golden = tmp_path / "golden.json"
    golden.write_text(json.dumps({"version": "golden-test", "cases": [
        {"id": "one", "query": "test"}, {"id": "two", "query": "test"},
    ]}), encoding="utf-8")
    monkeypatch.setattr(runner, "GOLDEN", golden)
    monkeypatch.setattr(runner, "REPORT_JSON", tmp_path / "report.json")
    monkeypatch.setattr(runner, "REPORT_MD", tmp_path / "report.md")
    monkeypatch.setattr(runner, "GraphRunner", lambda settings: object())

    async def result(case, *_args):
        assert not runner.REPORT_JSON.exists()
        return {"id": case["id"], "passed": False, "latency_ms": 100,
                "tool_accuracy": 0.5, "failure_stage": "retrieve"}

    monkeypatch.setattr(runner, "run_case", result)
    assert await runner.main(None, 0, environment="staging",
                             settings=Settings(_env_file=None, **settings_overrides)) == 0
    report = json.loads(runner.REPORT_JSON.read_text(encoding="utf-8"))
    assert report["status"] == "completed"
    assert report["selected_cases"] == report["metrics"]["cases"] == 2
    assert report["source"]["environment"] == "staging"
    assert report["source"]["llm_configured"] is False
    assert report["source"]["embedding_configured"] is (retrieval == "hybrid")
    assert report["source"]["configured_retrieval_mode"] == retrieval
    assert report["source"]["tool_data_source"] == "sample"
    assert report["source"]["agent_flags"]["mode"] == "graph"
    assert report["source"]["golden_set_version"] == "golden-test"
    assert len(report["git_sha"]) == 40
    assert report["id"]


async def test_runner_abort_never_overwrites_previous_report(tmp_path, monkeypatch):
    from evals import runner

    golden = tmp_path / "golden.json"
    golden.write_text(json.dumps({"version": "test", "cases": [{"id": "one"}]}))
    report = tmp_path / "report.json"
    report.write_text("previous report")
    monkeypatch.setattr(runner, "GOLDEN", golden)
    monkeypatch.setattr(runner, "REPORT_JSON", report)
    monkeypatch.setattr(runner, "REPORT_MD", tmp_path / "report.md")
    monkeypatch.setattr(runner, "get_settings", lambda: Settings(_env_file=None))
    monkeypatch.setattr(runner, "GraphRunner", lambda settings: object())

    async def fail(*_args):
        raise RuntimeError("interrupted")

    monkeypatch.setattr(runner, "run_case", fail)
    with pytest.raises(RuntimeError, match="interrupted"):
        await runner.main(None, 0, environment="staging")
    assert report.read_text() == "previous report"


async def test_runner_refuses_production_environment_and_empty_selection(monkeypatch):
    from evals import runner

    monkeypatch.setattr(runner, "get_settings", lambda: Settings(
        _env_file=None, app_env="production",
    ))
    with pytest.raises(ValueError, match="production"):
        await runner.main(1, 0)
    monkeypatch.setattr(runner, "get_settings", lambda: Settings(_env_file=None))
    with pytest.raises(ValueError, match="No evaluation cases"):
        await runner.main(None, 10000)


def test_isolated_evaluation_disables_paid_services_by_default():
    from scripts.evaluate_isolated import evaluation_settings

    settings = Settings(_env_file=None, app_env="production", llm_api_key="private",
                        embedding_api_key="private", rerank_enabled=True, rerank_api_key="private")
    isolated = evaluation_settings(settings, with_model=False)
    assert isolated.app_env == "staging"
    assert isolated.llm_api_key == isolated.embedding_api_key == isolated.rerank_api_key == ""
    assert not isolated.rerank_enabled
    assert settings.llm_api_key == "private"


@pytest.mark.parametrize("with_model", [False, True])
def test_isolated_evaluation_never_uses_shared_redis(with_model):
    from scripts.evaluate_isolated import evaluation_settings

    settings = Settings(_env_file=None, redis_url="redis://shared-production-cache")
    assert evaluation_settings(settings, with_model).redis_url == ""


def test_isolated_schema_url_uses_direct_endpoint_and_never_accepts_public():
    from scripts.evaluate_isolated import isolated_url

    settings = Settings(_env_file=None, database_url=(
        "postgresql+asyncpg://user:password@ep-test-pooler.region.neon.tech/test?sslmode=require"
    ))
    scoped = isolated_url(settings, "agentops_eval_" + "a" * 32)
    assert scoped.host == "ep-test.region.neon.tech"
    assert scoped.query["options"] == "-csearch_path=agentops_eval_" + "a" * 32
    with pytest.raises(ValueError):
        isolated_url(settings, "public")
