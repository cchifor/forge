"""In-process LRU cache adapter — TTL-aware ``CachePort`` implementation.

Suitable for single-replica dev/test workloads and per-process micro-
caches (e.g. JWKS, hot config). Multi-replica deployments should pick
the Redis adapter so eviction is consistent across pods.

The LRU eviction order is maintained by an ``OrderedDict``; TTL
expiry is checked lazily on read (cheap O(1) timestamp compare). A
background sweep would be overkill for the in-process tier — entries
that are never read again simply get evicted under capacity pressure.
"""

from __future__ import annotations

import asyncio
import os
import time
from collections import OrderedDict
from typing import Any

from app.ports.cache import CachePort

# Tunable via env so generated services can override without a code
# change. 1024 keys is a sane dev/test default; production single-
# replica workloads typically want 10k+ and a Redis upgrade past that.
_DEFAULT_MAX_ENTRIES = 1024


def _max_entries() -> int:
    raw = os.environ.get("CACHE_MEMORY_MAX_ENTRIES")
    if not raw:
        return _DEFAULT_MAX_ENTRIES
    try:
        parsed = int(raw)
    except ValueError:
        return _DEFAULT_MAX_ENTRIES
    return parsed if parsed > 0 else _DEFAULT_MAX_ENTRIES


class MemoryCacheAdapter(CachePort):
    def __init__(self, *, max_entries: int | None = None) -> None:
        self._max_entries = max_entries if max_entries is not None else _max_entries()
        # value, expires_at_monotonic (None = no expiry)
        self._store: OrderedDict[str, tuple[Any, float | None]] = OrderedDict()
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> Any | None:
        async with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            value, expires_at = entry
            if expires_at is not None and time.monotonic() >= expires_at:
                # Lazy expiry — drop and report miss.
                self._store.pop(key, None)
                return None
            # LRU bump on read.
            self._store.move_to_end(key)
            return value

    async def set(self, key: str, value: Any, ttl_seconds: int | None = None) -> None:
        async with self._lock:
            if ttl_seconds is not None and ttl_seconds <= 0:
                # Write-but-immediately-expired — treat as invalidate.
                self._store.pop(key, None)
                return
            expires_at: float | None = (
                None if ttl_seconds is None else time.monotonic() + ttl_seconds
            )
            self._store[key] = (value, expires_at)
            self._store.move_to_end(key)
            # Evict oldest entries until under the soft cap.
            while len(self._store) > self._max_entries:
                self._store.popitem(last=False)

    async def invalidate(self, key: str) -> None:
        async with self._lock:
            self._store.pop(key, None)
