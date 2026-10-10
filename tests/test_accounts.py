"""Real SQL transactions for account flows and cross-user authorization (SQLite)."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles

from apps.api.src.deps import db_dep, settings_dep
from apps.api.src.main import create_app
from apps.api.src.routers import runs
from apps.api.src.schemas.events import make_event
from apps.api.src.sse import bus
from src.auth import _attempts, token_digest
from src.config import Settings
from src.db.models import (
    AuthSession,
    AuthToken,
    Base,
    Chunk,
    Document,
    Run,
    Session,
    Ticket,
    Trace,
    User,
)

PASSWORD = "account-test-password"


@compiles(JSONB, "sqlite")
def sqlite_json(type_, compiler, **kwargs):
    return "JSON"


@compiles(TSVECTOR, "sqlite")
def sqlite_tsv(type_, compiler, **kwargs):
    return "TEXT"


@pytest.fixture
async def account_app(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'accounts.db'}")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(
            lambda conn: Base.metadata.create_all(
                conn,
                tables=[
                    model.__table__
                    for model in (
                        User,
                        AuthSession,
                        AuthToken,
                        Session,
                        Run,
                        Document,
                        Chunk,
                        Trace,
                        Ticket,
                    )
                ],
            )
        )
    settings = Settings(_env_file=None, auth_session_hours=8)
    monkeypatch.setattr("apps.api.src.main.get_settings", lambda: settings)
    app = create_app()

    async def database():
        async with factory() as db:
            yield db

    app.dependency_overrides[db_dep] = database
    app.dependency_overrides[settings_dep] = lambda: settings
    monkeypatch.setattr(runs, "get_session_factory", lambda settings: factory)
    mail = []

    async def send(settings, email, token, purpose):
        mail.append({"email": email, "token": token, "purpose": purpose})

    monkeypatch.setattr("src.auth.send_account_email", send)
    _attempts.clear()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client, factory, mail, settings
    for task in list(runs._tasks.values()):
        if not task.done():
            task.cancel()
    await asyncio.gather(*runs._tasks.values(), return_exceptions=True)
    runs._tasks.clear()
    _attempts.clear()
    await engine.dispose()


async def signup(client, mail, email="alice@example.com"):
    result = await client.post(
        "/auth/register",
        json={
            "email": email,
            "password": PASSWORD,
            "display_name": "Test user",
        },
    )
    assert result.status_code == 202
    return mail[-1]["token"]


async def signed_in(client, mail, email="alice@example.com"):
    token = await signup(client, mail, email)
    assert (await client.post("/auth/verify-email", json={"token": token})).status_code == 200
    result = await client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert result.status_code == 200
    return {"Authorization": f"Bearer {result.json()['token']}"}


async def test_signup_verify_login_logout(account_app):
    client, factory, mail, _ = account_app
    token = await signup(client, mail, "Alice@example.com")
    payload = {"email": "alice@example.com", "password": PASSWORD}
    assert (await client.post("/auth/login", json=payload)).status_code == 403
    assert (await client.post("/auth/verify-email", json={"token": token})).status_code == 200
    assert (await client.post("/auth/verify-email", json={"token": token})).status_code == 400
    response = await client.post("/auth/login", json=payload)
    headers = {"Authorization": f"Bearer {response.json()['token']}"}
    session = await client.get("/auth/session", headers=headers)
    assert session.json()["user"]["email"] == "alice@example.com"
    assert session.json()["user"]["role"] == "member"
    async with factory() as db:
        stored = await db.scalar(select(AuthSession))
        assert stored.token_hash == token_digest(response.json()["token"])
        assert stored.token_hash != response.json()["token"]
        user = await db.scalar(select(User))
        assert user.password_hash != PASSWORD
    assert (await client.post("/auth/logout", headers=headers)).status_code == 200
    assert (await client.get("/auth/session", headers=headers)).status_code == 401


async def test_registration_cannot_change_password_or_assign_admin(account_app):
    client, factory, mail, _ = account_app
    headers = await signed_in(client, mail)
    duplicate = await client.post(
        "/auth/register",
        json={
            "email": "ALICE@example.com",
            "password": "attacker-password",
            "display_name": "Attacker",
        },
    )
    assert duplicate.status_code == 202
    assert len(mail) == 1
    assert (
        await client.post(
            "/auth/login",
            json={
                "email": "alice@example.com",
                "password": PASSWORD,
            },
        )
    ).status_code == 200
    assert (
        await client.post(
            "/auth/register",
            json={
                "email": "bob@example.com",
                "password": PASSWORD,
                "display_name": "Bob",
                "role": "admin",
            },
        )
    ).status_code == 422
    assert (await client.get("/eval/report", headers=headers)).status_code == 403
    async with factory() as db:
        user = await db.scalar(select(User))
        user.role = "admin"
        await db.commit()
    assert (await client.get("/eval/report", headers=headers)).status_code == 200


async def test_reset_revokes_all_sessions_and_is_single_use(account_app):
    client, factory, mail, _ = account_app
    first = await signed_in(client, mail)
    second_response = await client.post(
        "/auth/login",
        json={
            "email": "alice@example.com",
            "password": PASSWORD,
        },
    )
    second = {"Authorization": f"Bearer {second_response.json()['token']}"}
    request = {"email": "alice@example.com"}
    response = await client.post("/auth/forgot-password", json=request)
    unknown = await client.post("/auth/forgot-password", json={"email": "unknown@example.com"})
    assert response.json() == unknown.json()
    token = mail[-1]["token"]
    assert (await client.post("/auth/verify-email", json={"token": token})).status_code == 400
    payload = {"token": token, "password": "new-test-password"}
    assert (await client.post("/auth/reset-password", json=payload)).status_code == 200
    assert (await client.post("/auth/reset-password", json=payload)).status_code == 400
    for headers in (first, second):
        assert (await client.get("/auth/session", headers=headers)).status_code == 401
    assert (
        await client.post("/auth/login", json={**request, "password": PASSWORD})
    ).status_code == 401
    assert (
        await client.post("/auth/login", json={**request, "password": payload["password"]})
    ).status_code == 200


async def test_expired_replaced_tokens_and_disabled_accounts(account_app):
    client, factory, mail, _ = account_app
    old = await signup(client, mail)
    assert (
        await client.post("/auth/resend-verification", json={"email": "alice@example.com"})
    ).status_code == 202
    assert (await client.post("/auth/verify-email", json={"token": old})).status_code == 400
    token = mail[-1]["token"]
    async with factory() as db:
        await db.execute(
            update(AuthToken).values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
        await db.commit()
    assert (await client.post("/auth/verify-email", json={"token": token})).status_code == 400
    headers = await signed_in(client, mail, "bob@example.com")
    async with factory() as db:
        await db.execute(
            update(AuthSession).values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
        await db.commit()
    assert (await client.get("/auth/session", headers=headers)).status_code == 401
    async with factory() as db:
        await db.execute(update(User).values(is_active=False))
        await db.commit()
    assert (
        await client.post("/auth/login", json={"email": "bob@example.com", "password": PASSWORD})
    ).status_code == 401


async def test_mail_failure_does_not_create_a_fake_success(account_app, monkeypatch):
    from fastapi import HTTPException

    client, factory, mail, _ = account_app

    async def fail(*args):
        raise HTTPException(503, "mail unavailable")

    monkeypatch.setattr("src.auth.send_account_email", fail)
    response = await client.post(
        "/auth/register",
        json={
            "email": "alice@example.com",
            "password": PASSWORD,
            "display_name": "Alice",
        },
    )
    assert response.status_code == 503
    async with factory() as db:
        assert await db.scalar(select(User)) is None


async def test_all_run_endpoints_reject_cross_user_access(account_app):
    client, factory, mail, _ = account_app
    alice = await signed_in(client, mail)
    bob = await signed_in(client, mail, "bob@example.com")
    response = await client.post("/sessions", json={"title": "Private"}, headers=alice)
    session_id = response.json()["id"]
    assert [item["id"] for item in (await client.get("/sessions", headers=alice)).json()] == [
        session_id
    ]
    assert (await client.get("/sessions", headers=bob)).json() == []
    run_id = uuid.uuid4()
    async with factory() as db:
        db.add(Run(id=run_id, session_id=uuid.UUID(session_id), status="awaiting_approval"))
        await db.commit()
    bus.publish(make_event(type="token", run_id=str(run_id), payload={"delta": "alice secret"}))
    for path in (f"/runs/{run_id}/stream", f"/runs/{run_id}/status", f"/traces/{run_id}"):
        assert (await client.get(path, headers=bob)).status_code == 404
        assert (await client.get(path)).status_code == 401
    for path, payload in ((f"/runs/{run_id}/resume", {"ok": True}), (f"/runs/{run_id}/abort", {})):
        assert (await client.post(path, json=payload, headers=bob)).status_code == 404
    assert (
        await client.post("/runs", json={"session_id": session_id, "query": "steal"}, headers=bob)
    ).status_code == 404
    assert (await client.get(f"/runs/{run_id}/status", headers=alice)).json()[
        "state"
    ] == "awaiting_approval"
    assert (await client.get(f"/traces/{run_id}", headers=alice)).status_code == 200
    assert (await client.post(f"/runs/{run_id}/abort", headers=alice)).status_code == 200
    assert (
        await client.post(f"/runs/{run_id}/resume", json={"ok": True}, headers=alice)
    ).status_code == 409


async def test_gateway_secret_alone_does_not_allow_business_access(account_app):
    client, _, _, settings = account_app
    settings.api_token = "gateway"
    assert (await client.get("/sessions", headers={"X-API-Token": "gateway"})).status_code == 401
    assert (
        await client.get("/sessions", headers={"Authorization": "Bearer gateway"})
    ).status_code == 401


async def test_run_daily_and_concurrency_limits(account_app):
    client, factory, mail, settings = account_app
    headers = await signed_in(client, mail)
    session_id = (await client.post("/sessions", json={"title": "Quota"}, headers=headers)).json()[
        "id"
    ]
    async with factory() as db:
        db.add(Run(session_id=uuid.UUID(session_id), status="awaiting_approval"))
        await db.commit()
    settings.max_active_runs_per_user = 1
    payload = {"session_id": session_id, "query": "hello"}
    assert (await client.post("/runs", json=payload, headers=headers)).status_code == 429
    async with factory() as db:
        await db.execute(update(Run).values(status="completed"))
        await db.commit()
    settings.max_runs_per_user_per_day = 1
    assert (await client.post("/runs", json=payload, headers=headers)).status_code == 429


async def test_session_runs_restore_completed_output(account_app):
    client, factory, mail, _ = account_app
    headers = await signed_in(client, mail)
    session_id = (await client.post("/sessions", json={"title": "历史"}, headers=headers)).json()[
        "id"
    ]
    run_id = uuid.uuid4()
    async with factory() as db:
        db.add(
            Run(
                id=run_id,
                session_id=uuid.UUID(session_id),
                status="completed",
                query="昨晚报警",
                answer="已完成定位",
                citations=[{"chunk_id": "c1"}],
                tool_results=[{"name": "query_metrics", "ok": True}],
            )
        )
        await db.commit()

    response = await client.get(f"/sessions/{session_id}/runs", headers=headers)
    assert response.status_code == 200
    snapshot = response.json()[0]
    assert snapshot["id"] == str(run_id)
    assert snapshot["answer"] == "已完成定位"
    assert snapshot["citations"] == [{"chunk_id": "c1"}]


async def test_completed_run_persists_echo_output(account_app):
    client, factory, mail, _ = account_app
    headers = await signed_in(client, mail)
    session_id = (await client.post("/sessions", json={"title": "执行"}, headers=headers)).json()[
        "id"
    ]
    response = await client.post(
        "/runs", json={"session_id": session_id, "query": "hello"}, headers=headers
    )
    assert response.status_code == 201
    run_id = response.json()["id"]
    await asyncio.gather(*runs._tasks.values())
    async with factory() as db:
        stored = await db.scalar(select(Run).where(Run.id == uuid.UUID(run_id)))
        assert stored.status == "completed"
        assert stored.answer == "hello"


@pytest.mark.parametrize("approved", [False, True])
async def test_local_api_restores_plan_and_resumes_approval_once(
    account_app, monkeypatch, approved
):
    from src.tools.registry import ToolRegistry

    client, factory, mail, settings = account_app
    settings.agent_mode = "graph"
    settings.agent_conditional_routing = True
    settings.agent_targeted_retry = True
    monkeypatch.setattr("src.db.session.get_session_factory", lambda _: factory)
    monkeypatch.setattr("src.tools.registry._registry", ToolRegistry(settings))
    headers = await signed_in(client, mail)
    session_id = (await client.post(
        "/sessions", json={"title": "Local approval"}, headers=headers
    )).json()["id"]
    response = await client.post(
        "/runs", json={"session_id": session_id, "query": "创建 P1 工单"}, headers=headers
    )
    assert response.status_code == 201
    run_id = response.json()["id"]
    await runs._tasks[run_id]
    snapshot = (await client.get(f"/sessions/{session_id}/runs", headers=headers)).json()[0]
    assert snapshot["status"] == "awaiting_approval"
    assert snapshot["plan"]["version"] == 1
    approval_id = snapshot["approval"]["approval_id"]
    write = next(step for step in snapshot["plan"]["steps"] if step["tool"] == "create_ticket")
    assert approval_id == f"{run_id}:{write['id']}"
    assert any(result["name"] == "search_code" for result in snapshot["tool_results"])
    async with factory() as db:
        assert await db.scalar(select(Ticket)) is None
    assert (await client.post(
        f"/runs/{run_id}/resume", json={"ok": approved, "approval_id": "stale"}, headers=headers
    )).status_code == 409

    # New-run switches must not change a waiting run's graph or checkpoint.
    settings.agent_conditional_routing = False
    settings.agent_targeted_retry = False
    decision = {"ok": approved, "approval_id": approval_id}
    assert (await client.post(
        f"/runs/{run_id}/resume", json=decision, headers=headers
    )).status_code == 200
    await runs._tasks[f"{run_id}:resume"]
    assert (await client.post(
        f"/runs/{run_id}/resume", json=decision, headers=headers
    )).status_code == 409
    restored = (await client.get(f"/sessions/{session_id}/runs", headers=headers)).json()[0]
    assert restored["status"] == ("completed" if approved else "rejected")
    assert restored["approval"] == {}
    assert sum(result["name"] == "create_ticket" for result in restored["tool_results"]) == 1
    async with factory() as db:
        tickets = list(await db.scalars(select(Ticket)))
        assert len(tickets) == int(approved)
        if approved:
            assert tickets[0].idempotency_key == approval_id


async def test_document_upload_passes_server_identity_and_enforces_limits(account_app, monkeypatch):
    client, _, mail, settings = account_app
    headers = await signed_in(client, mail)
    user_id = (await client.get("/auth/session", headers=headers)).json()["user"]["id"]
    captured = []

    async def ingest(**kwargs):
        captured.append(kwargs["owner_id"])
        return uuid.uuid4(), 1, 0

    monkeypatch.setattr("src.rag.ingest.ingest_document", ingest)
    settings.database_url = "configured"
    settings.max_ingests_per_user_per_day = 1
    payload = {"title": "Private", "content": "private knowledge"}
    assert (await client.post("/ingest", json=payload, headers=headers)).status_code == 201
    assert captured == [uuid.UUID(user_id)]
    assert (await client.post("/ingest", json=payload, headers=headers)).status_code == 429


async def test_auth_limits_apply_before_password_checks_or_mail(account_app):
    client, _, mail, _ = account_app
    for _ in range(10):
        response = await client.post(
            "/auth/login", json={"email": "unknown@example.com", "password": "wrong"}
        )
        assert response.status_code == 401
    response = await client.post(
        "/auth/login", json={"email": "unknown@example.com", "password": "wrong"}
    )
    assert response.status_code == 429
    assert response.headers["Retry-After"]
    for _ in range(5):
        assert (
            await client.post("/auth/forgot-password", json={"email": "unknown@example.com"})
        ).status_code == 202
    assert (
        await client.post("/auth/forgot-password", json={"email": "unknown@example.com"})
    ).status_code == 429
    assert mail == []


async def test_disabled_user_loses_existing_session(account_app):
    client, factory, mail, _ = account_app
    headers = await signed_in(client, mail)
    async with factory() as db:
        await db.execute(update(User).values(is_active=False))
        await db.commit()
    assert (await client.get("/auth/session", headers=headers)).status_code == 401
    assert (await client.get("/sessions", headers=headers)).status_code == 401


async def test_database_evaluation_requires_verified_resource_owner(account_app, monkeypatch):
    from evals.runner import _create_eval_run

    client, factory, mail, settings = account_app
    monkeypatch.setattr("evals.runner.get_session_factory", lambda settings: factory)
    with pytest.raises(ValueError, match="requires --user-id"):
        await _create_eval_run(str(uuid.uuid4()), "Private evaluation", settings)
    await signup(client, mail)
    async with factory() as db:
        user = await db.scalar(select(User))
        user_id = str(user.id)
    with pytest.raises(ValueError, match="active and verified"):
        await _create_eval_run(str(uuid.uuid4()), "Private evaluation", settings, user_id)
    await client.post("/auth/verify-email", json={"token": mail[-1]["token"]})
    run_id = uuid.uuid4()
    await _create_eval_run(str(run_id), "Private evaluation", settings, user_id)
    async with factory() as db:
        session = await db.scalar(select(Session).join(Run).where(Run.id == run_id))
        assert session.owner_id == uuid.UUID(user_id)


async def test_accounts_fail_closed_without_database(account_app):
    client, _, _, _ = account_app
    app = client._transport.app

    async def unavailable():
        yield None

    app.dependency_overrides[db_dep] = unavailable
    assert (
        await client.post("/auth/login", json={"email": "alice@example.com", "password": PASSWORD})
    ).status_code == 503
    assert (
        await client.get("/sessions", headers={"Authorization": "Bearer pretend-token"})
    ).status_code == 503


async def ticket_run(client, factory, headers, query="订单服务 P1 故障，需要建单"):
    session_id = (await client.post("/sessions", json={"title": "Ticket"}, headers=headers)).json()[
        "id"
    ]
    user_id = (await client.get("/auth/session", headers=headers)).json()["user"]["id"]
    run_id = uuid.uuid4()
    async with factory() as db:
        db.add(Run(id=run_id, session_id=uuid.UUID(session_id), query=query, status="running"))
        await db.commit()
    return uuid.UUID(user_id), run_id


async def test_ticket_approval_persists_once_and_archived_retry_fails(account_app, monkeypatch):
    from datetime import UTC, datetime

    from src.agent.runner import GraphRunner
    from src.tools.registry import ToolRegistry

    client, factory, mail, settings = account_app
    headers = await signed_in(client, mail)
    user_id, run_id = await ticket_run(client, factory, headers)
    monkeypatch.setattr("src.db.session.get_session_factory", lambda _settings: factory)
    monkeypatch.setattr("src.tools.registry._registry", ToolRegistry(settings))
    events = []

    async def emit(event):
        events.append(event)

    runner = GraphRunner(settings)
    await runner.run(str(run_id), "创建 P1 工单", emit, user_id=str(user_id))
    async with factory() as db:
        assert (await db.execute(select(Ticket))).scalars().all() == []
    approval = next(event.payload for event in events if event.type == "hitl_request")
    assert approval["args"]["title"] == "创建 P1 工单"
    assert approval["args"]["severity"] == "P1"
    await runner.resume(
        str(run_id),
        {
            "ok": True,
            "approval_id": approval["approval_id"],
            "args": {
                "title": "Edited title",
                "severity": "P0",
                "detail": "Private detail",
                "idempotency_key": "user-controlled-key",
            },
        },
        emit,
        user_id=str(user_id),
    )
    result = next(
        event.payload
        for event in events
        if event.type == "tool_result" and event.payload["name"] == "create_ticket"
    )
    assert result["ok"] is True
    assert result["args"]["idempotency_key"] == f"{run_id}:tool-1"
    from src.agent.context import bind
    from src.tools.builtin import create_ticket

    bind(user_id=str(user_id), run_id=str(run_id), settings=settings, write_approved=True)
    try:
        repeated = await create_ticket(result["args"])
        assert repeated["ticket_id"] == result["output"]["ticket_id"]
        async with factory() as db:
            tickets = (await db.execute(select(Ticket))).scalars().all()
            assert len(tickets) == 1
            assert tickets[0].title == "Edited title"
            assert tickets[0].severity == "P0"
            assert tickets[0].status == "created"
            tickets[0].archived_at = datetime.now(UTC)
            await db.commit()
        with pytest.raises(ValueError, match="archived"):
            await create_ticket(result["args"])
    finally:
        bind(user_id="", run_id="", write_approved=False)


async def test_rejected_ticket_never_persists(account_app, monkeypatch):
    from src.agent.runner import GraphRunner
    from src.tools.registry import ToolRegistry

    client, factory, mail, settings = account_app
    headers = await signed_in(client, mail)
    user_id, run_id = await ticket_run(client, factory, headers)
    monkeypatch.setattr("src.db.session.get_session_factory", lambda _settings: factory)
    monkeypatch.setattr("src.tools.registry._registry", ToolRegistry(settings))

    async def emit(event):
        pass

    runner = GraphRunner(settings)
    await runner.run(str(run_id), "创建工单", emit, user_id=str(user_id))
    await runner.resume(str(run_id), {
        "ok": False, "approval_id": (await runner.approval(str(run_id)))["approval_id"],
    }, emit, user_id=str(user_id))
    async with factory() as db:
        assert (await db.execute(select(Ticket))).scalars().all() == []


async def test_ticket_backfill_merges_skips_conflicts_and_preserves_edits(account_app):
    from src.db.ticket_backfill import backfill_tickets

    client, factory, mail, _ = account_app
    headers = await signed_in(client, mail)
    _, run_id = await ticket_run(client, factory, headers)

    def result(number, title):
        return {
            "name": "create_ticket",
            "ok": True,
            "args": {"detail": "original detail"},
            "output": {"ticket_id": number, "title": title, "severity": "P1"},
        }

    async with factory() as db:
        run = await db.get(Run, run_id)
        run.tool_results = [
            result("OPS-10001", "Valid"),
            result("OPS-10001", "Valid"),
            result("OPS-10002", "First"),
            result("OPS-10002", "Conflicting"),
            result("OPS-10003", ""),
            {"name": "create_ticket", "ok": False, "output": {"ticket_id": "OPS-10004"}},
        ]
        await db.commit()
        conn = await db.connection()
        report = await conn.run_sync(backfill_tickets)
        await db.commit()
        assert report == {"imported": 1, "existing": 0, "invalid": 1, "conflicts": 1}
        ticket = await db.scalar(select(Ticket))
        assert ticket.ticket_id == "OPS-10001"
        ticket.title = "User edit"
        await db.commit()
        conn = await db.connection()
        assert (await conn.run_sync(backfill_tickets))["existing"] == 1
        await db.commit()
        await db.refresh(ticket)
        assert ticket.title == "User edit"


async def test_ticket_overview_edit_archive_and_user_isolation(account_app):
    from src.tickets import TicketFields, persist_ticket

    client, factory, mail, _ = account_app
    alice = await signed_in(client, mail)
    bob = await signed_in(client, mail, "bob@example.com")
    alice_id, run_id = await ticket_run(client, factory, alice)
    bob_id, bob_run = await ticket_run(client, factory, bob)
    async with factory() as db:
        for i in range(21):
            await persist_ticket(
                db,
                owner_id=alice_id,
                run_id=run_id,
                fields=TicketFields(title=f"Ticket {i}"),
                idempotency_key=str(i),
            )
        other = await persist_ticket(
            db,
            owner_id=bob_id,
            run_id=bob_run,
            fields=TicketFields(title="Private"),
            idempotency_key="0",
        )
    listing = (await client.get("/tickets", headers=alice)).json()
    assert listing["total"] == 21
    assert len(listing["items"]) == 20
    assert len((await client.get("/tickets?page=2", headers=alice)).json()["items"]) == 1
    assert (await client.get("/tickets", headers=bob)).json()["total"] == 1
    assert (await client.get("/tickets?page=0", headers=alice)).status_code == 422
    ticket = listing["items"][0]
    fields = {"title": "Edited", "detail": "Detail", "severity": "P0", "status": "in_progress"}
    assert (
        await client.patch(f"/tickets/{other.id}", json=fields, headers=alice)
    ).status_code == 404
    assert (await client.delete(f"/tickets/{ticket['id']}", headers=bob)).status_code == 404
    for invalid in (
        {"severity": "P4"},
        {"status": "running"},
        {"title": "  "},
        {"owner_id": str(bob_id)},
    ):
        assert (
            await client.patch(
                f"/tickets/{ticket['id']}", json={**fields, **invalid}, headers=alice
            )
        ).status_code == 422
    saved = await client.patch(f"/tickets/{ticket['id']}", json=fields, headers=alice)
    assert saved.status_code == 200
    assert saved.json()["status"] == "in_progress"
    assert saved.json()["ticket_id"] == ticket["ticket_id"]
    refreshed = (await client.get("/tickets", headers=alice)).json()
    assert refreshed["items"][0]["title"] == "Edited"
    assert (await client.delete(f"/tickets/{ticket['id']}", headers=alice)).status_code == 200
    assert (await client.get("/tickets", headers=alice)).json()["total"] == 20
    assert (
        await client.patch(f"/tickets/{ticket['id']}", json=fields, headers=alice)
    ).status_code == 404
    async with factory() as db:
        assert (await db.get(Ticket, uuid.UUID(ticket["id"]))).archived_at is not None


async def test_ticket_commit_failure_never_reports_success(account_app, monkeypatch):
    from sqlalchemy.exc import SQLAlchemyError
    from sqlalchemy.ext.asyncio import AsyncSession

    from src.agent.context import bind
    from src.tools.registry import ToolRegistry

    client, factory, mail, settings = account_app
    headers = await signed_in(client, mail)
    owner_id, run_id = await ticket_run(client, factory, headers)
    monkeypatch.setattr("src.db.session.get_session_factory", lambda _settings: factory)

    async def fail_commit(self):
        raise SQLAlchemyError("test database failure")

    monkeypatch.setattr(AsyncSession, "commit", fail_commit)
    bind(user_id=str(owner_id), run_id=str(run_id), settings=settings, write_approved=True)
    try:
        result = await ToolRegistry(settings).call(
            "create_ticket", {"title": "Failure", "idempotency_key": "failure"}
        )
        assert result.ok is False
        assert result.output is None
        async with factory() as db:
            assert await db.scalar(select(Ticket)) is None
    finally:
        bind(user_id="", run_id="", write_approved=False)


async def test_chunk_preview_uses_uuid_and_enforces_document_owner(account_app):
    client, factory, mail, _ = account_app
    alice = await signed_in(client, mail)
    bob = await signed_in(client, mail, "bob@example.com")
    owner_id, _ = await ticket_run(client, factory, alice)
    async with factory() as db:
        first = Document(title="First", source="https://example.com/first", owner_id=owner_id)
        second = Document(title="Second", owner_id=owner_id)
        db.add_all([first, second])
        await db.flush()
        a = Chunk(
            document_id=first.id,
            chunk_id="same-hash",
            content="Original text",
            meta={"heading": "Section"},
        )
        b = Chunk(document_id=second.id, chunk_id="same-hash", content="Original text")
        db.add_all([a, b])
        await db.commit()
    preview = await client.get(f"/documents/{first.id}/chunks/{a.id}", headers=alice)
    assert preview.status_code == 200
    assert preview.json()["content"] == "Original text"
    assert preview.json()["heading"] == "Section"
    assert preview.json()["source_url"] == "https://example.com/first"
    assert (
        await client.get(f"/documents/{first.id}/chunks/{a.id}", headers=bob)
    ).status_code == 404
    assert (
        await client.get(f"/documents/{first.id}/chunks/{b.id}", headers=alice)
    ).status_code == 404
    other = await client.get(f"/documents/{second.id}/chunks/{b.id}", headers=alice)
    assert other.json()["title"] == "Second"


async def test_retrieval_diagnostics_survive_refresh_and_partial_completion(account_app):
    client, factory, mail, settings = account_app
    headers = await signed_in(client, mail)
    _, run_id = await ticket_run(client, factory, headers)
    diagnosis = {"mode": "graph", "status": "no_match", "reason": "no_match"}
    await runs._persist_run_result(
        str(run_id),
        settings,
        make_event(
            type="retrieve", run_id=str(run_id), payload={"citations": [], "retrieval": diagnosis}
        ),
    )
    async with factory() as db:
        session_id = (await db.get(Run, run_id)).session_id
    snapshot = (await client.get(f"/sessions/{session_id}/runs", headers=headers)).json()[0]
    assert snapshot["retrieval"] == diagnosis
    await runs._persist_run_result(
        str(run_id),
        settings,
        make_event(
            type="done",
            run_id=str(run_id),
            payload={"answer": "No evidence", "citations": [], "retrieval": diagnosis},
        ),
    )
    await runs._persist_run_result(
        str(run_id),
        settings,
        make_event(type="done", run_id=str(run_id), payload={"aborted": True}),
    )
    refreshed = (await client.get(f"/sessions/{session_id}/runs", headers=headers)).json()[0]
    assert refreshed["retrieval"] == diagnosis
    assert refreshed["answer"] == "No evidence"


@pytest.mark.parametrize("outcome", ["no_documents", "no_match", "hit", "unavailable"])
async def test_retrieval_reports_empty_library_matches_and_failure(
    account_app, monkeypatch, outcome
):
    import importlib

    from src.agent.context import bind
    from src.agent.nodes.retrieve import retrieve
    from src.rag.hybrid_search import ChunkHit

    client, factory, mail, settings = account_app
    headers = await signed_in(client, mail)
    user_id, run_id = await ticket_run(client, factory, headers)
    monkeypatch.setattr(
        importlib.import_module("src.agent.nodes.retrieve"),
        "get_session_factory",
        lambda _: factory,
    )
    async with factory() as db:
        if outcome != "no_documents":
            doc = Document(owner_id=user_id, title="Manual")
            db.add(doc)
            await db.flush()
            db.add(Chunk(document_id=doc.id, chunk_id="hash", content="Text"))
            await db.commit()
    calls = []

    async def search(query, **kwargs):
        calls.append(kwargs["owner_id"])
        if outcome == "unavailable":
            raise RuntimeError("private credentials must not enter events")
        return (
            [ChunkHit(chunk_id="hash", citation_id=str(uuid.uuid4()))] if outcome == "hit" else []
        )

    monkeypatch.setattr("src.rag.hybrid_search.hybrid_search", search)
    events = []

    async def emit(event):
        events.append(event)

    bind(user_id=str(user_id), settings=settings, emit=emit)
    try:
        result = await retrieve({"query": "Query", "run_id": str(run_id)})
        assert result["retrieval"]["status"] == outcome
        assert bool(result["citations"]) == (outcome == "hit")
        assert calls == ([] if outcome == "no_documents" else [str(user_id)])
        assert "private credentials" not in str(events)
    finally:
        bind(user_id="", emit=None)
