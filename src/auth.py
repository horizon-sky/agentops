"""Password hashing, single-use mail tokens, session lookup and abuse limits."""

from __future__ import annotations

import asyncio
import hashlib
import secrets
from collections import OrderedDict, deque
from datetime import UTC, datetime, timedelta
from time import monotonic
from urllib.parse import urlencode, urlparse

import httpx
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import Settings
from src.db.models import AuthSession, AuthToken, User

password_hasher = PasswordHasher()
# Keep failed lookups comparable to password verification without hashing on every request.
_dummy_hash = password_hasher.hash(secrets.token_urlsafe(32))
_attempts: OrderedDict[str, deque[float]] = OrderedDict()


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def rate_limit(key: str, limit: int, window_s: int = 600) -> None:
    """Single-replica limiter; keys are hashes and the store is bounded."""
    key = token_digest(key)
    now = monotonic()
    attempts = _attempts.setdefault(key, deque())
    _attempts.move_to_end(key)
    while attempts and attempts[0] <= now - window_s:
        attempts.popleft()
    if len(attempts) >= limit:
        raise HTTPException(429, "请求过于频繁，请稍后再试", headers={"Retry-After": str(window_s)})
    attempts.append(now)
    while len(_attempts) > 10000:
        _attempts.popitem(last=False)


async def hash_password(password: str) -> str:
    return await asyncio.to_thread(password_hasher.hash, password)


async def verify_password(password: str, password_hash: str | None) -> bool:
    def verify() -> bool:
        try:
            valid = password_hasher.verify(password_hash or _dummy_hash, password)
            return valid and password_hash is not None
        except (VerificationError, InvalidHashError):
            return False

    return await asyncio.to_thread(verify)


async def lookup_session(db: AsyncSession, token: str) -> tuple[User, AuthSession] | None:
    if not token or len(token) > 256:
        return None
    result = await db.execute(
        select(User, AuthSession)
        .join(AuthSession, AuthSession.user_id == User.id)
        .where(
            AuthSession.token_hash == token_digest(token),
            AuthSession.expires_at > datetime.now(UTC),
            AuthSession.revoked_at.is_(None),
            User.is_active.is_(True),
            User.verified_at.is_not(None),
        )
        .execution_options(populate_existing=True)
    )
    row = result.first()
    return (row[0], row[1]) if row else None


async def send_account_email(settings: Settings, email: str, token: str, purpose: str) -> None:
    origin = settings.web_origin.rstrip("/")
    parsed = urlparse(origin)
    if not settings.resend_api_key or not settings.mail_from:
        raise HTTPException(503, "邮件服务尚未配置，请联系管理员")
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(503, "邮件链接配置无效")
    if settings.app_env == "production" and parsed.scheme != "https":
        raise HTTPException(503, "生产环境邮件链接必须使用 HTTPS")
    page = "verify-email" if purpose == "verify" else "reset-password"
    label = "验证邮箱" if purpose == "verify" else "重置密码"
    # Fragment stays out of HTTP access logs and Referer headers.
    link = f"{origin}/{page}#{urlencode({'token': token})}"
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {settings.resend_api_key}"},
                json={
                    "from": settings.mail_from,
                    "to": [email],
                    "subject": f"AgentOps · {label}",
                    "text": f"请打开以下链接并确认{label}：\n{link}\n链接有效期为 30 分钟。",
                },
            )
            response.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(503, "邮件发送失败，请稍后重试") from exc


async def issue_mail_token(db: AsyncSession, user: User, purpose: str, settings: Settings) -> None:
    # Lock the user to serialize issue/consume operations for this account.
    await db.execute(select(User.id).where(User.id == user.id).with_for_update())
    now = datetime.now(UTC)
    await db.execute(
        update(AuthToken)
        .where(
            AuthToken.user_id == user.id, AuthToken.purpose == purpose, AuthToken.used_at.is_(None)
        )
        .values(used_at=now)
    )
    token = secrets.token_urlsafe(32)
    db.add(
        AuthToken(
            user_id=user.id,
            purpose=purpose,
            token_hash=token_digest(token),
            expires_at=now + timedelta(minutes=30),
        )
    )
    await db.flush()
    await send_account_email(settings, user.email, token, purpose)


async def consume_mail_token(db: AsyncSession, token: str, purpose: str) -> User:
    token_hash = token_digest(token)
    # Lock the user first, the same order as issue_mail_token/password reset.
    user_id = await db.scalar(select(AuthToken.user_id).where(AuthToken.token_hash == token_hash))
    if user_id is None:
        raise HTTPException(400, "链接无效或已过期，请重新申请")
    user = await db.scalar(select(User).where(User.id == user_id).with_for_update())
    if user is None or not user.is_active:
        raise HTTPException(400, "链接无效或已过期，请重新申请")
    now = datetime.now(UTC)
    claimed = await db.scalar(
        update(AuthToken)
        .where(
            AuthToken.token_hash == token_hash,
            AuthToken.purpose == purpose,
            AuthToken.expires_at > now,
            AuthToken.used_at.is_(None),
        )
        .values(used_at=now)
        .returning(AuthToken.id)
    )
    if claimed is None:
        raise HTTPException(400, "链接无效或已过期，请重新申请")
    return user
