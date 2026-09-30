"""检查点装配：使用可回收连接池避免 Neon 空闲连接失效。"""

from __future__ import annotations

from contextlib import AsyncExitStack

from langgraph.checkpoint.base import BaseCheckpointSaver

from src.config import Settings


async def build_checkpointer(
    settings: Settings, stack: AsyncExitStack
) -> tuple[BaseCheckpointSaver, bool]:
    """返回 (checkpointer, 是否持久化)。"""
    if settings.has_database:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
        from psycopg.rows import dict_row
        from psycopg_pool import AsyncConnectionPool

        url = settings.database_url.replace("postgresql+asyncpg://", "postgresql://", 1)
        if url.startswith("postgresql+psycopg://"):
            url = url.replace("postgresql+psycopg://", "postgresql://", 1)
        pool = AsyncConnectionPool(
            url,
            kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
            min_size=1,
            max_size=4,
            max_lifetime=300,
            max_idle=60,
            check=AsyncConnectionPool.check_connection,
            open=False,
        )
        await stack.enter_async_context(pool)
        saver = AsyncPostgresSaver(conn=pool)
        await saver.setup()
        return saver, True

    from langgraph.checkpoint.memory import MemorySaver

    return MemorySaver(), False
