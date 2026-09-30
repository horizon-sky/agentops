from fastapi import HTTPException

from apps.api.src.deps import require_token
from src.config import Settings


def test_auth_allows_when_token_is_unconfigured() -> None:
    require_token(None, None, Settings(_env_file=None, api_token=""))


def test_auth_accepts_bearer_token() -> None:
    require_token(None, "Bearer secret", Settings(_env_file=None, api_token="secret"))


def test_auth_accepts_legacy_header() -> None:
    require_token("secret", None, Settings(_env_file=None, api_token="secret"))


def test_auth_rejects_missing_or_invalid_token() -> None:
    settings = Settings(_env_file=None, api_token="secret")
    for legacy, authorization in [(None, None), (None, "Bearer wrong"), ("wrong", None)]:
        try:
            require_token(legacy, authorization, settings)
        except HTTPException as exc:
            assert exc.status_code == 401
        else:
            raise AssertionError("expected 401")
