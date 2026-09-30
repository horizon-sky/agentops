"""异步数据库会话与初始化。

无 DATABASE_URL 时不会抛错，而是返回 None，由上层降级处理，
保证「本地无数据库也能启动服务跑通链路」。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from src.config import Settings

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine(settings: Settings) -> AsyncEngine | None:
    global _engine
    if _engine is not None:
        return _engine
    if not settings.has_database:
        return None
    # Railway / Neon 均为托管连接池，使用 NullPool 避免连接被应用侧长期占用
    database_url = make_url(settings.database_url)
    if database_url.drivername in {"postgresql", "postgres"}:
        database_url = database_url.set(drivername="postgresql+asyncpg")
    elif database_url.drivername == "postgresql+psycopg":
        database_url = database_url.set(drivername="postgresql+asyncpg")
    if "sslmode" in database_url.query and "ssl" not in database_url.query:
        database_url = database_url.update_query_dict({"ssl": database_url.query["sslmode"]})
        database_url = database_url.difference_update_query(["sslmode"])
    if "channel_binding" in database_url.query:
        database_url = database_url.difference_update_query(["channel_binding"])
    _engine = create_async_engine(
        database_url.render_as_string(hide_password=False),
        poolclass=NullPool,
        echo=False,
        future=True,
    )
    return _engine


def get_session_factory(settings: Settings) -> async_sessionmaker[AsyncSession] | None:
    global _session_factory
    if _session_factory is not None:
        return _session_factory
    engine = get_engine(settings)
    if engine is None:
        return None
    _session_factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    return _session_factory


async def get_db(settings: Settings) -> AsyncIterator[AsyncSession | None]:
    """FastAPI 依赖：无数据库时注入 None，路由层需自行处理。"""
    factory = get_session_factory(settings)
    if factory is None:
        yield None
        return
    async with factory() as session:
        yield session


async def init_db(settings: Settings) -> bool:
    """仅检查数据库可用性；表结构由 Alembic 迁移管理。"""
    engine = get_engine(settings)
    if engine is None:
        return False
    async with engine.begin() as conn:
        await conn.execute(text("SELECT 1"))
    return True


async def dispose_engine() -> None:
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None


async def db_status(settings: Settings) -> dict[str, Any]:
    if not settings.has_database:
        return {"connected": False, "mode": "memory-fallback"}
    try:
        engine = get_engine(settings)
        if engine is None:
            raise RuntimeError("database engine unavailable")
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return {"connected": True, "mode": "postgres"}
    except Exception as exc:  # noqa: BLE001 - health endpoint must report state
        return {"connected": False, "mode": "postgres", "error": str(exc)[:160]}
