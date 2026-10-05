"""FastAPI 依赖：配置、缓存、缓存键与轻量鉴权。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from secrets import compare_digest
from uuid import UUID

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import lookup_session
from src.config import Settings, get_settings
from src.db.cache import Cache, build_cache
from src.db.models import AuthSession, Run, Session, User
from src.db.session import get_db

_cache: Cache | None = None


def settings_dep() -> Settings:
    return get_settings()


def cache_dep() -> Cache:
    global _cache
    if _cache is None:
        _cache = build_cache(get_settings())
    return _cache


async def db_dep(settings: Settings = Depends(settings_dep)) -> AsyncIterator[AsyncSession | None]:
    """注入数据库会话；未配置数据库时为 None，由路由层降级处理。"""
    try:
        async for session in get_db(settings):
            yield session
    except SQLAlchemyError as exc:
        raise HTTPException(503, "数据库暂时不可用") from exc


def require_gateway(
    x_api_token: str | None = Header(default=None),
    settings: Settings = Depends(settings_dep),
) -> None:
    """Optional server-to-server credential, never a user identity."""
    if settings.app_env == "production" and not settings.api_token:
        raise HTTPException(503, "服务端代理鉴权尚未配置")
    if settings.api_token and not compare_digest(x_api_token or "", settings.api_token):
        raise HTTPException(401, "invalid gateway credential")


async def auth_db(db: AsyncSession | None = Depends(db_dep)) -> AsyncSession:
    if db is None:
        raise HTTPException(503, "账号系统需要配置数据库")
    return db


@dataclass
class Principal:
    user: User
    session: AuthSession
    token: str


async def current_user(
    authorization: str | None = Header(default=None),
    _gateway: None = Depends(require_gateway),
    db: AsyncSession | None = Depends(db_dep),
) -> Principal:
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(401, "authentication required")
    if db is None:
        raise HTTPException(503, "账号系统需要配置数据库")
    identity = await lookup_session(db, token)
    if identity is None:
        raise HTTPException(401, "登录已过期，请重新登录")
    return Principal(*identity, token)


async def admin_user(identity: Principal = Depends(current_user)) -> Principal:
    if identity.user.role != "admin":
        raise HTTPException(403, "需要管理员权限")
    return identity


def client_ip(request: Request, settings: Settings) -> str:
    # Only trust the proxy's overwritten address after the gateway credential is checked.
    if settings.api_token:
        return request.headers.get("x-agentops-client-ip", "unknown")[:100]
    return request.client.host if request.client else "unknown"


async def owned_session(db: AsyncSession, session_id: UUID, user_id: UUID) -> Session:
    session = await db.scalar(
        select(Session).where(Session.id == session_id, Session.owner_id == user_id)
    )
    if session is None:
        raise HTTPException(404, "会话不存在")
    return session


async def owned_run(db: AsyncSession, run_id: UUID, user_id: UUID, *, lock: bool = False) -> Run:
    query = select(Run).join(Session).where(Run.id == run_id, Session.owner_id == user_id)
    if lock:
        query = query.with_for_update(of=Run)
    run = await db.scalar(query)
    if run is None:
        raise HTTPException(404, "运行不存在")
    return run


def idempotency_key(prefix: str, key: str) -> str:
    return f"idem:{prefix}:{key}"
