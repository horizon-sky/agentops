from __future__ import annotations

import asyncio
import copy
import json
import uuid
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from test_accounts import account_app as account_app
from test_accounts import signed_in

from src.db.models import Document, EvalRun, Run, Session, Ticket, User


def report_payload(**changes):
    payload = {
        "schema_version": 1,
        "id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        "status": "completed",
        "started_at": "2026-10-12T00:00:00Z",
        "generated_at": "2026-10-12T00:01:00Z",
        "git_sha": "a" * 40,
        "prompt_version": "test-prompt",
        "model_version": "test-model",
        "selected_cases": 2,
        "source": {
            "environment": "staging",
            "golden_set_version": "test-golden",
            "code_dirty": False,
            "cheap_model": "test-model-cheap",
            "llm_configured": True,
            "database_configured": True,
            "embedding_configured": False,
            "rerank_configured": False,
            "configured_retrieval_mode": "bm25",
            "tool_data_source": "sample",
            "agent_flags": {"mode": "graph", "routing": False,
                            "retry": False, "dynamic": False},
        },
        "metrics": {
            "cases": 2, "citation_skipped": 0,
            "task_success_rate": 50.0, "tool_accuracy": 75.0,
            "recall_at_5": None, "p50_latency_ms": 100.0, "p95_latency_ms": 200.0,
            "avg_tokens": None, "cost_per_task": None,
            "failure_stages": {"retrieve": 1},
        },
        "results": [{"query": "private test query", "answer": "private test answer"}],
    }
    payload.update(changes)
    return payload


def test_completed_report_accepts_failed_cases_without_leaking_details():
    from src.eval_report import CompletedEvalReport

    report = CompletedEvalReport.model_validate(report_payload())
    summary = report.model_dump(mode="json")
    assert summary["metrics"]["task_success_rate"] == 50.0
    assert summary["metrics"]["cost_per_task"] is None
    assert "results" not in summary
    assert "private test" not in json.dumps(summary)


@pytest.mark.parametrize("change", [
    {"status": "running"}, {"schema_version": 0}, {"git_sha": "unknown"},
    {"generated_at": "2026-10-11T00:00:00Z"},
    {"generated_at": "2026-10-12T00:01:00"},
    {"selected_cases": 3}, {"selected_cases": 0},
    {"source": {}}, {"metrics": {}},
])
def test_incomplete_or_legacy_reports_cannot_publish(change):
    from src.eval_report import CompletedEvalReport

    with pytest.raises(ValidationError):
        CompletedEvalReport.model_validate(report_payload(**change))


@pytest.mark.parametrize("key,value", [
    ("task_success_rate", 101.0), ("tool_accuracy", float("nan")),
    ("p95_latency_ms", -1.0), ("cases", True), ("citation_skipped", 3),
    ("failure_stages", {"retrieve": -1}),
])
def test_invalid_metrics_cannot_publish(key, value):
    from src.eval_report import CompletedEvalReport

    payload = report_payload()
    payload["metrics"][key] = value
    with pytest.raises(ValidationError):
        CompletedEvalReport.model_validate(payload)


async def make_admin(client, factory, mail):
    headers = await signed_in(client, mail)
    async with factory() as db:
        user = await db.scalar(select(User))
        user.role = "admin"
        user.verified_at = datetime.now(UTC)
        await db.commit()
        email = user.email
    return headers, email


async def test_eval_api_permissions_and_empty_report(account_app):
    client, factory, mail, _ = account_app
    assert (await client.get("/eval/report")).status_code == 401
    headers = await signed_in(client, mail)
    assert (await client.get("/eval/report", headers=headers)).status_code == 403
    async with factory() as db:
        user = await db.scalar(select(User))
        user.role = "admin"
        await db.commit()
    response = await client.get("/eval/report", headers=headers)
    assert response.status_code == 200
    assert response.json()["status"] == "empty"
    assert response.json()["metrics"] == {}
    assert response.json()["generated_at"] is None
    assert response.json()["report_path"] == ""


async def test_publish_persists_summary_is_idempotent_and_survives_new_session(account_app):
    from src.db.eval_reports import publish_report
    from src.eval_report import CompletedEvalReport

    client, factory, mail, _ = account_app
    headers, email = await make_admin(client, factory, mail)
    report = CompletedEvalReport.model_validate(report_payload())
    async with factory() as db:
        assert await publish_report(db, report, email) is True
    async with factory() as db:
        assert await publish_report(db, report, email.upper()) is False
        assert await db.scalar(select(func.count()).select_from(EvalRun)) == 1
        for model in (Document, Run, Session, Ticket):
            assert await db.scalar(select(func.count()).select_from(model)) == 0
        row = await db.get(EvalRun, report.id)
        assert "private test" not in json.dumps(row.metrics)
        assert "private test" not in json.dumps(row.source)
    response = await client.get("/eval/report", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["id"] == str(report.id)
    assert body["metrics"]["task_success_rate"] == 50.0
    assert body["source"]["environment"] == "staging"
    assert datetime.fromisoformat(body["generated_at"]).replace(tzinfo=UTC) == datetime(
        2026, 10, 12, 0, 1, tzinfo=UTC,
    )
    assert body["git_sha"] == "a" * 40
    assert (await client.get("/eval/report", headers=headers)).json() == body


async def test_older_publication_and_legacy_rows_do_not_replace_latest(account_app):
    from src.db.eval_reports import publish_report
    from src.eval_report import CompletedEvalReport

    client, factory, mail, _ = account_app
    headers, email = await make_admin(client, factory, mail)
    latest = CompletedEvalReport.model_validate(report_payload())
    older = CompletedEvalReport.model_validate(report_payload(
        id=str(uuid.uuid4()), started_at="2026-10-11T00:00:00Z",
        generated_at="2026-10-11T00:01:00Z",
    ))
    async with factory() as db:
        await publish_report(db, latest, email)
    async with factory() as db:
        await publish_report(db, older, email)
        db.add(EvalRun(metrics={"task_success_rate": 99.0}))
        await db.commit()
    response = await client.get("/eval/report", headers=headers)
    assert response.json()["id"] == str(latest.id)


async def test_same_id_different_summary_is_rejected(account_app):
    from src.db.eval_reports import publish_report
    from src.eval_report import CompletedEvalReport

    client, factory, mail, _ = account_app
    _, email = await make_admin(client, factory, mail)
    payload = report_payload()
    async with factory() as db:
        await publish_report(db, CompletedEvalReport.model_validate(payload), email)
    changed = copy.deepcopy(payload)
    changed["metrics"]["tool_accuracy"] = 25.0
    async with factory() as db:
        with pytest.raises(ValueError, match="different content"):
            await publish_report(db, CompletedEvalReport.model_validate(changed), email)
    async with factory() as db:
        row = await db.get(EvalRun, uuid.UUID(payload["id"]))
        assert row.metrics["tool_accuracy"] == 75.0


async def test_two_administrators_can_publish_the_same_report_concurrently(
    account_app, monkeypatch,
):
    from sqlalchemy.ext.asyncio import AsyncSession

    from src.db.eval_reports import publish_report
    from src.eval_report import CompletedEvalReport

    client, factory, mail, _ = account_app
    _, email = await make_admin(client, factory, mail)
    async with factory() as db:
        db.add(User(email="second-admin@example.com", display_name="Second",
                    password_hash="unused", role="admin", verified_at=datetime.now(UTC)))
        await db.commit()
    report = CompletedEvalReport.model_validate(report_payload())
    real_get = AsyncSession.get
    both_read = asyncio.Event()
    reads = 0

    async def synchronized_get(db, model, key, **kwargs):
        nonlocal reads
        row = await real_get(db, model, key, **kwargs)
        if model is EvalRun and key == report.id and row is None:
            reads += 1
            if reads == 2:
                both_read.set()
            await asyncio.wait_for(both_read.wait(), timeout=5)
        return row

    monkeypatch.setattr(AsyncSession, "get", synchronized_get)

    async def send(address):
        async with factory() as db:
            return await publish_report(db, report, address)

    result = await asyncio.gather(send(email), send("second-admin@example.com"))
    assert sorted(result) == [False, True]
    async with factory() as db:
        assert await db.scalar(select(func.count()).select_from(EvalRun)) == 1


@pytest.mark.parametrize("role,verified,active", [
    ("member", True, True), ("admin", False, True), ("admin", True, False),
])
async def test_publication_requires_verified_active_admin(account_app, role, verified, active):
    from src.db.eval_reports import publish_report
    from src.eval_report import CompletedEvalReport

    client, factory, mail, _ = account_app
    _, email = await make_admin(client, factory, mail)
    async with factory() as db:
        user = await db.scalar(select(User))
        user.role = role
        user.verified_at = datetime.now(UTC) if verified else None
        user.is_active = active
        await db.commit()
    async with factory() as db:
        with pytest.raises(ValueError, match="verified, active administrator"):
            await publish_report(db, CompletedEvalReport.model_validate(report_payload()), email)
        assert await db.scalar(select(func.count()).select_from(EvalRun)) == 0


async def test_eval_database_failure_is_503_not_empty(account_app, monkeypatch):
    from src.db import eval_reports

    client, factory, mail, _ = account_app
    headers, _ = await make_admin(client, factory, mail)

    async def failed_read(db):
        raise SQLAlchemyError("private connection details")

    monkeypatch.setattr(eval_reports, "latest_report", failed_read)
    response = await client.get("/eval/report", headers=headers)
    assert response.status_code == 503
    assert "private connection" not in response.text


async def test_publish_commit_failure_rolls_back(account_app, monkeypatch):
    from src.db.eval_reports import publish_report
    from src.eval_report import CompletedEvalReport

    client, factory, mail, _ = account_app
    _, email = await make_admin(client, factory, mail)
    async with factory() as db:
        async def failed_commit():
            raise SQLAlchemyError("commit failed")

        monkeypatch.setattr(db, "commit", failed_commit)
        with pytest.raises(SQLAlchemyError):
            await publish_report(db, CompletedEvalReport.model_validate(report_payload()), email)
    async with factory() as db:
        assert await db.scalar(select(func.count()).select_from(EvalRun)) == 0


async def test_publication_script_uses_target_database_and_only_summary(
    account_app, tmp_path, monkeypatch,
):
    from scripts import publish_eval_report

    client, factory, mail, settings = account_app
    _, email = await make_admin(client, factory, mail)
    report_file = tmp_path / "report.json"
    report_file.write_text(json.dumps(report_payload()), encoding="utf-8")
    monkeypatch.setattr(publish_eval_report, "get_settings", lambda: settings)
    monkeypatch.setattr(publish_eval_report, "get_session_factory", lambda _settings: factory)
    assert await publish_eval_report.publish(report_file, email) is True
    assert await publish_eval_report.publish(report_file, email) is False
    async with factory() as db:
        assert await db.scalar(select(func.count()).select_from(EvalRun)) == 1


def test_publication_cli_invalid_file_exits_nonzero_without_success(tmp_path, monkeypatch, capsys):
    from scripts import publish_eval_report

    report_file = tmp_path / "report.json"
    report_file.write_text('{"metrics": {}}')
    monkeypatch.setattr("sys.argv", ["publish_eval_report", "--report", str(report_file),
                                     "--email", "admin@example.com"])
    assert publish_eval_report.main() == 1
    output = capsys.readouterr()
    assert "[FAIL]" in output.err
    assert "[ OK ]" not in output.out


def test_publication_cli_database_failure_never_prints_credentials(tmp_path, monkeypatch, capsys):
    from scripts import publish_eval_report

    report_file = tmp_path / "report.json"
    report_file.write_text(json.dumps(report_payload()))
    monkeypatch.setattr("sys.argv", ["publish_eval_report", "--report", str(report_file),
                                     "--email", "admin@example.com"])

    async def fail(*args):
        raise SQLAlchemyError("postgres://private-password@host")

    monkeypatch.setattr(publish_eval_report, "publish", fail)
    assert publish_eval_report.main() == 1
    output = capsys.readouterr()
    assert "[FAIL]" in output.err
    assert "private-password" not in output.err
    assert "[ OK ]" not in output.out
