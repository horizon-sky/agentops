"""Registration challenges exercise the HTTP contract and persisted single-use behavior."""

from __future__ import annotations

import asyncio
import base64
import uuid
from datetime import UTC, datetime, timedelta
from io import BytesIO

import pytest
from sqlalchemy import func, select, text

from src.db.models import User
from tests import test_accounts

PASSWORD = test_accounts.PASSWORD
account_app = test_accounts.account_app


async def challenge(client):
    response = await client.post("/auth/captcha")
    assert response.status_code == 200
    return response.json()


def registration(captcha, email="captcha@example.com", answer="AAAAA"):
    return {
        "email": email,
        "password": PASSWORD,
        "display_name": "Captcha user",
        "captcha_id": captcha["captcha_id"],
        "captcha_answer": answer,
    }


async def test_captcha_returns_png_without_answer_and_cleans_expired_rows(account_app, monkeypatch):
    client, factory, _, _ = account_app
    monkeypatch.setattr("secrets.choice", lambda alphabet: alphabet[0])
    response = await client.post("/auth/captcha")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    data = response.json()
    assert set(data) == {"captcha_id", "image_data_url", "expires_at"}
    uuid.UUID(data["captcha_id"])
    assert (
        290
        < (datetime.fromisoformat(data["expires_at"]) - datetime.now(UTC)).total_seconds()
        <= 300
    )
    from PIL import Image

    image = Image.open(BytesIO(base64.b64decode(data["image_data_url"].split(",", 1)[1])))
    assert image.format == "PNG"
    assert not image.info
    async with factory() as db:
        await db.execute(
            text("UPDATE auth_captchas SET expires_at=:expired"),
            {
                "expired": datetime.now(UTC) - timedelta(seconds=1),
            },
        )
        await db.commit()
    await challenge(client)
    async with factory() as db:
        assert await db.scalar(text("SELECT count(*) FROM auth_captchas")) == 1


@pytest.mark.parametrize("answer", ["aaaaa", "AAAAA"])
async def test_register_without_mail_then_login_keeps_email_unverified(
    account_app, monkeypatch, answer
):
    client, factory, mail, _ = account_app
    monkeypatch.setattr("secrets.choice", lambda alphabet: alphabet[0])
    captcha = await challenge(client)
    response = await client.post("/auth/register", json=registration(captcha, answer=answer))
    assert response.status_code == 201
    assert set(response.json()) == {"message"}
    assert mail == []
    async with factory() as db:
        user = await db.scalar(select(User))
        assert user.verified_at is None
        assert user.role == "member"
    login = await client.post(
        "/auth/login", json={"email": "captcha@example.com", "password": PASSWORD}
    )
    assert login.status_code == 200
    headers = {"Authorization": f"Bearer {login.json()['token']}"}
    assert (await client.get("/auth/session", headers=headers)).status_code == 200
    assert (
        await client.post("/sessions", json={"title": "Own"}, headers=headers)
    ).status_code == 200
    assert (
        await client.post("/auth/register", json=registration(captcha, email="other@example.com"))
    ).status_code == 400


@pytest.mark.parametrize("failure", ["wrong", "expired", "unknown"])
async def test_invalid_challenge_is_consumed_without_creating_account(
    account_app, monkeypatch, failure
):
    client, factory, _, _ = account_app
    monkeypatch.setattr("secrets.choice", lambda alphabet: alphabet[0])
    captcha = await challenge(client)
    if failure == "expired":
        async with factory() as db:
            await db.execute(
                text("UPDATE auth_captchas SET expires_at=:expired"),
                {
                    "expired": datetime.now(UTC) - timedelta(seconds=1),
                },
            )
            await db.commit()
    if failure == "unknown":
        captcha["captcha_id"] = str(uuid.uuid4())
    payload = registration(captcha, answer="BBBBB" if failure == "wrong" else "AAAAA")
    assert (await client.post("/auth/register", json=payload)).status_code == 400
    payload["captcha_answer"] = "AAAAA"
    assert (await client.post("/auth/register", json=payload)).status_code == 400
    async with factory() as db:
        assert await db.scalar(select(func.count()).select_from(User)) == 0


async def test_missing_captcha_is_rejected(account_app):
    client, factory, _, _ = account_app
    payload = {"email": "missing@example.com", "password": PASSWORD, "display_name": "Missing"}
    assert (await client.post("/auth/register", json=payload)).status_code == 422
    async with factory() as db:
        assert await db.scalar(select(User)) is None


async def test_same_captcha_can_create_only_one_account_concurrently(account_app, monkeypatch):
    client, factory, _, _ = account_app
    monkeypatch.setattr("secrets.choice", lambda alphabet: alphabet[0])
    captcha = await challenge(client)
    responses = await asyncio.gather(
        *[
            client.post("/auth/register", json=registration(captcha, email=f"race{i}@example.com"))
            for i in range(2)
        ]
    )
    assert sorted(response.status_code for response in responses) == [201, 400]
    async with factory() as db:
        assert await db.scalar(select(func.count()).select_from(User)) == 1


async def test_duplicate_email_race_preserves_original_account(account_app, monkeypatch):
    client, factory, _, _ = account_app
    monkeypatch.setattr("secrets.choice", lambda alphabet: alphabet[0])
    captchas = [await challenge(client) for _ in range(2)]
    responses = await asyncio.gather(
        *[client.post("/auth/register", json=registration(captcha)) for captcha in captchas]
    )
    assert sorted(response.status_code for response in responses) == [201, 409]
    for captcha in captchas:
        assert (
            await client.post("/auth/register", json=registration(captcha, email="new@example.com"))
        ).status_code == 400
    async with factory() as db:
        assert await db.scalar(select(func.count()).select_from(User)) == 1


@pytest.mark.parametrize("integrity_failure", [False, True])
async def test_registration_commit_failure_does_not_restore_challenge(
    account_app, monkeypatch, integrity_failure
):
    from sqlalchemy.exc import IntegrityError, SQLAlchemyError
    from sqlalchemy.ext.asyncio import AsyncSession

    client, factory, _, _ = account_app
    monkeypatch.setattr("secrets.choice", lambda alphabet: alphabet[0])
    captcha = await challenge(client)
    original_commit = AsyncSession.commit

    from apps.api.src.deps import db_dep

    async def database(_settings):
        async with factory() as db:
            yield db

    monkeypatch.setattr("apps.api.src.deps.get_db", database)
    del client._transport.app.dependency_overrides[db_dep]

    async def fail_account_commit(self):
        if self.new:
            if integrity_failure:
                raise IntegrityError("INSERT", {}, Exception("constraint failure"))
            raise SQLAlchemyError("account commit failed")
        await original_commit(self)

    with monkeypatch.context() as scoped:
        scoped.setattr(AsyncSession, "commit", fail_account_commit)
        assert (await client.post("/auth/register", json=registration(captcha))).status_code == 503
    assert (await client.post("/auth/register", json=registration(captcha))).status_code == 400
    async with factory() as db:
        assert await db.scalar(select(User)) is None


async def test_captcha_generation_and_registration_limits(account_app, monkeypatch):
    client, _, _, _ = account_app
    monkeypatch.setattr("secrets.choice", lambda alphabet: alphabet[0])
    captcha = await challenge(client)
    for i in range(20):
        assert (
            await client.post(
                "/auth/register",
                json=registration(
                    captcha,
                    email=f"limit{i}@example.com",
                    answer="BBBBB",
                ),
            )
        ).status_code == 400
    assert (await client.post("/auth/register", json=registration(captcha))).status_code == 429
    for _ in range(29):
        await challenge(client)
    assert (await client.post("/auth/captcha")).status_code == 429


async def test_registration_email_limit_does_not_consume_another_challenge(account_app):
    client, _, _, _ = account_app
    captcha = await challenge(client)
    for _ in range(10):
        assert (
            await client.post(
                "/auth/register",
                json=registration(captcha, answer="BBBBB"),
            )
        ).status_code == 400
    unused = await challenge(client)
    assert (await client.post("/auth/register", json=registration(unused))).status_code == 429
    assert (
        await client.post(
            "/auth/register",
            json=registration(unused, email="allowed@example.com"),
        )
    ).status_code == 201


async def test_legacy_unverified_user_can_login_without_changing_verification(account_app):
    from src.auth import hash_password

    client, factory, _, _ = account_app
    async with factory() as db:
        db.add(
            User(
                email="legacy@example.com",
                display_name="Legacy",
                password_hash=await hash_password(PASSWORD),
                verified_at=None,
            )
        )
        await db.commit()
    login = await client.post(
        "/auth/login", json={"email": "legacy@example.com", "password": PASSWORD}
    )
    assert login.status_code == 200
    assert (
        await client.get(
            "/auth/session",
            headers={
                "Authorization": f"Bearer {login.json()['token']}",
            },
        )
    ).status_code == 200
    async with factory() as db:
        assert (await db.scalar(select(User))).verified_at is None
