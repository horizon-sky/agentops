"""检查点装配：数据库配置存在时保持 Postgres 连接到应用关闭。"""

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

        url = settings.database_url.replace("postgresql+asyncpg://", "postgresql://", 1)
        saver = await stack.enter_async_context(AsyncPostgresSaver.from_conn_string(url))
        await saver.setup()
        return saver, True

    from langgraph.checkpoint.memory import MemorySaver

    return MemorySaver(), False
