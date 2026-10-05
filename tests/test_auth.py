from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException

from apps.api.src.deps import require_gateway
from src.auth import _attempts, hash_password, rate_limit, verify_password
from src.config import Settings


def test_gateway_credential_cannot_be_used_as_a_user_identity() -> None:
    settings = Settings(_env_file=None, api_token="gateway")
    require_gateway("gateway", settings)
    with pytest.raises(HTTPException) as error:
        require_gateway("wrong", settings)
    assert error.value.status_code == 401


def test_production_cannot_disable_gateway_authentication() -> None:
    with pytest.raises(HTTPException) as error:
        require_gateway(None, Settings(_env_file=None, app_env="production"))
    assert error.value.status_code == 503


async def test_passwords_are_hashed_and_wrong_passwords_rejected() -> None:
    password_hash = await hash_password("my secure password")
    assert password_hash.startswith("$argon2id$")
    assert await verify_password("my secure password", password_hash)
    assert not await verify_password("wrong password", password_hash)
    assert not await verify_password("wrong password", None)


def test_limiter_rejects_before_more_expensive_operations(monkeypatch) -> None:
    _attempts.clear()
    now = datetime.now(UTC).timestamp()
    monkeypatch.setattr("src.auth.monotonic", lambda: now)
    rate_limit("test", 1)
    with pytest.raises(HTTPException) as error:
        rate_limit("test", 1)
    assert error.value.status_code == 429
    now += timedelta(minutes=11).total_seconds()
    rate_limit("test", 1)
    _attempts.clear()


async def test_missing_mail_configuration_returns_503():
    from src.auth import send_account_email

    with pytest.raises(HTTPException) as error:
        await send_account_email(Settings(_env_file=None), "alice@example.com", "secret", "verify")
    assert error.value.status_code == 503
