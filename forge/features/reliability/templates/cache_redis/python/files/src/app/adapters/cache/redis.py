"""Redis cache adapter — ``CachePort`` implementation backed by redis-py asyncio.

Picked up when ``reliability.cache=redis`` is set. Values are stored
as JSON; non-JSON-serialisable values raise ``TypeError`` at ``set``
time. Cross-replica safe — eviction is governed by Redis's
``maxmemory-policy`` (usually ``allkeys-lru``).

Shares the Redis sidecar with queue/rate-limit fragments via the
standard ``REDIS_URL`` env var; consider running cache traffic on a
dedicated database number (default ``/3``) to avoid eviction clobbering
queue keysets.
"""

from __future__ import annotations

import json
import os
from typing import Any

import redis.asyncio as redis

from app.ports.cache import CachePort

# Use a dedicated DB to keep cache eviction policy independent from
# queue (db=0/2) and rate-limit (db=1) keyspaces. Override with
# ``CACHE_REDIS_URL`` if you want a different host/port too.
_DEFAULT_URL = "redis://redis:6379/3"


def _redis_url() -> str:
    return os.environ.get("CACHE_REDIS_URL", _DEFAULT_URL)


class RedisCacheAdapter(CachePort):
    def __init__(self, url: str | None = None) -> None:
        self._client = redis.from_url(url or _redis_url(), decode_responses=True)

    async def get(self, key: str) -> Any | None:
        raw = await self._client.get(key)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            # An adapter writer outside this codebase may have stored a
            # raw string under the same key (e.g. via redis-cli).
            # Falling back to the raw value matches the principle of
            # least surprise for ops users debugging cache misses.
            return raw

    async def set(self, key: str, value: Any, ttl_seconds: int | None = None) -> None:
        if ttl_seconds is not None and ttl_seconds <= 0:
            # Write-but-immediately-expired — semantically an invalidate.
            await self._client.delete(key)
            return
        payload = json.dumps(value)
        if ttl_seconds is None:
            await self._client.set(key, payload)
        else:
            await self._client.set(key, payload, ex=ttl_seconds)

    async def invalidate(self, key: str) -> None:
        await self._client.delete(key)
