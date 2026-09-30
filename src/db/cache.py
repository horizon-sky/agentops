"""缓存抽象：Redis 优先，未提供 REDIS_URL 时降级为进程内实现。

接口保持一致，调用方无需判断当前用的是哪一种实现；
`degraded=True` 用于判断是否处于降级状态（仅用于日志与 /healthz）。
"""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from src.config import Settings


@runtime_checkable
class Cache(Protocol):
    @property
    def degraded(self) -> bool: ...

    async def get(self, key: str) -> Any | None: ...

    async def set(self, key: str, value: Any, ttl_s: int = 300) -> None: ...

    async def delete(self, key: str) -> None: ...

    async def set_if_absent(self, key: str, value: Any, ttl_s: int = 300) -> bool:
        """幂等键实现：返回 True 表示本次成功占位（首次执行）。"""
        ...


class InMemoryCache:
    def __init__(self, max_items: int = 2000) -> None:
        self._store: dict[str, tuple[float, str]] = {}
        self._max_items = max_items

    @property
    def degraded(self) -> bool:
        return True

    def _evict_if_needed(self) -> None:
        if len(self._store) <= self._max_items:
            return
        now = time.time()
        expired = [key for key, (expire_at, _) in self._store.items() if expire_at <= now]
        for key in expired:
            self._store.pop(key, None)
        while len(self._store) > self._max_items:
            self._store.pop(next(iter(self._store)), None)

    async def get(self, key: str) -> Any | None:
        item = self._store.get(key)
        if item is None:
            return None
        expire_at, raw = item
        if expire_at <= time.time():
            self._store.pop(key, None)
            return None
        return json.loads(raw)

    async def set(self, key: str, value: Any, ttl_s: int = 300) -> None:
        self._store[key] = (time.time() + ttl_s, json.dumps(value, ensure_ascii=False))
        self._evict_if_needed()

    async def delete(self, key: str) -> None:
        self._store.pop(key, None)

    async def set_if_absent(self, key: str, value: Any, ttl_s: int = 300) -> bool:
        current = await self.get(key)
        if current is not None:
            return False
        await self.set(key, value, ttl_s)
        return True


class RedisCache:
    def __init__(self, url: str) -> None:
        self._url = url
        self._client: Any | None = None

    @property
    def degraded(self) -> bool:
        return False

    def _ensure_client(self) -> Any:
        if self._client is None:
            import redis.asyncio as redis  # 延迟导入，未配置 Redis 时不引入依赖

            self._client = redis.from_url(self._url, decode_responses=True)
        return self._client

    async def get(self, key: str) -> Any | None:
        client = self._ensure_client()
        raw = await client.get(key)
        return json.loads(raw) if raw is not None else None

    async def set(self, key: str, value: Any, ttl_s: int = 300) -> None:
        client = self._ensure_client()
        await client.set(key, json.dumps(value, ensure_ascii=False), ex=ttl_s)

    async def delete(self, key: str) -> None:
        client = self._ensure_client()
        await client.delete(key)

    async def set_if_absent(self, key: str, value: Any, ttl_s: int = 300) -> bool:
        client = self._ensure_client()
        ok = await client.set(
            key, json.dumps(value, ensure_ascii=False), ex=ttl_s, nx=True
        )
        return bool(ok)


def build_cache(settings: Settings | None = None) -> Cache:
    if settings is None:
        from src.config import get_settings

        settings = get_settings()
    return RedisCache(settings.redis_url) if settings.redis_url else InMemoryCache()
