"""FastAPI 依赖：配置、缓存、缓存键与轻量鉴权。"""

from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import Settings, get_settings
from src.db.cache import Cache, build_cache
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
    async for session in get_db(settings):
        yield session


def require_token(
    x_api_token: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
    settings: Settings = Depends(settings_dep),
) -> None:
    """API_TOKEN 未配置时放行；配置后优先校验 Bearer，兼容旧请求头。"""
    if not settings.api_token:
        return
    bearer = None
    if authorization:
        scheme, _, value = authorization.partition(" ")
        if scheme.lower() == "bearer":
            bearer = value.strip()
    if (bearer or x_api_token) != settings.api_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid token")


def idempotency_key(prefix: str, key: str) -> str:
    return f"idem:{prefix}:{key}"
