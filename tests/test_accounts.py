"""Real SQL transactions for account flows and cross-user authorization (SQLite)."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles

from apps.api.src.deps import db_dep, settings_dep
from apps.api.src.main import create_app
from apps.api.src.routers import runs
from apps.api.src.schemas.events import make_event
from apps.api.src.sse import bus
from src.auth import _attempts, token_digest
from src.config import Settings
from src.db.models import AuthSession, AuthToken, Base, Document, Run, Session, Trace, User

PASSWORD = "account-test-password"


@compiles(JSONB, "sqlite")
def sqlite_json(type_, compiler, **kwargs):
    return "JSON"


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
                        Trace,
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
