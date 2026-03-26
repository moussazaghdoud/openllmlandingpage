"""Storage abstraction — Redis with in-memory fallback.

When Redis is unavailable (e.g., local dev), falls back to a dict-based
in-memory store with the same async interface.
"""

from __future__ import annotations

import logging
from typing import Protocol

import redis.asyncio as aioredis

from app.config import settings

logger = logging.getLogger("securellm.storage")


class KVStore(Protocol):
    async def get(self, key: str) -> str | None: ...
    async def set(self, key: str, value: str, ex: int | None = None) -> None: ...
    async def delete(self, *keys: str) -> None: ...
    async def scan_iter(self, match: str) -> list[str]: ...
    async def ping(self) -> bool: ...


class MemoryStore:
    """In-memory key-value store for local dev / testing."""

    def __init__(self) -> None:
        self._data: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self._data.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self._data[key] = value

    async def delete(self, *keys: str) -> None:
        for k in keys:
            self._data.pop(k, None)

    async def scan_iter(self, match: str) -> list[str]:
        import fnmatch
        return [k for k in self._data if fnmatch.fnmatch(k, match)]

    async def ping(self) -> bool:
        return True


class RedisStore:
    """Thin wrapper around aioredis to match KVStore interface."""

    def __init__(self, client: aioredis.Redis) -> None:
        self._r = client

    async def get(self, key: str) -> str | None:
        return await self._r.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        if ex:
            await self._r.set(key, value, ex=ex)
        else:
            await self._r.set(key, value)

    async def delete(self, *keys: str) -> None:
        if keys:
            await self._r.delete(*keys)

    async def scan_iter(self, match: str) -> list[str]:
        keys = []
        cursor = 0
        while True:
            cursor, batch = await self._r.scan(cursor, match=match, count=100)
            keys.extend(batch)
            if cursor == 0:
                break
        return keys

    async def ping(self) -> bool:
        return await self._r.ping()


_store: KVStore | None = None


async def get_store() -> KVStore:
    global _store
    if _store is not None:
        return _store

    # Try Redis first
    redis_url = settings.redis_url.strip()
    if redis_url and redis_url.startswith(("redis://", "rediss://", "unix://")):
        try:
            client = aioredis.from_url(
                redis_url, decode_responses=True, max_connections=20
            )
            await client.ping()
            _store = RedisStore(client)
            logger.info("Connected to Redis")
        except Exception as e:
            logger.warning("Redis unavailable (%s) — using in-memory store", e)
            _store = MemoryStore()
    else:
        if redis_url:
            logger.warning("Invalid REDIS_URL '%s' — using in-memory store", redis_url[:20])
        else:
            logger.info("No REDIS_URL set — using in-memory store")
        _store = MemoryStore()

    return _store


async def close_store() -> None:
    global _store
    if isinstance(_store, RedisStore):
        await _store._r.aclose()
    _store = None
