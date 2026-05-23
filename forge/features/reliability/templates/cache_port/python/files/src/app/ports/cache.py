"""Cache port — capability contract for generic key/value caching.

Distinct from ``app/core/response_cache.py`` (HTTP-response middleware
keyed on request shape via fastapi-cache2). This port is the **generic
K/V** surface — idempotency-key dedupe, LLM-response memoization,
denormalized read caches all sit on top of it.

Adapters live under ``app/adapters/cache/<provider>.py``. The port's
surface is intentionally minimal: ``get`` / ``set`` (with TTL) /
``invalidate``. Bulk and pattern-match operations are provider-
specific and stay inside adapters.
"""

from __future__ import annotations

from typing import Any, Protocol


class CachePort(Protocol):
    """Generic key/value cache. Values are JSON-serialisable.

    Adapters MUST tolerate concurrent ``get`` / ``set`` / ``invalidate``
    calls on the same key; an adapter that races on TTL eviction
    breaks the idempotency-key use case the port targets.
    """

    async def get(self, key: str) -> Any | None:
        """Return the cached value for ``key``, or ``None`` if missing or expired."""

    async def set(self, key: str, value: Any, ttl_seconds: int | None = None) -> None:
        """Store ``value`` under ``key``.

        ``ttl_seconds=None`` means "no expiry" — the entry lives until
        explicitly invalidated or evicted by the adapter's own pressure
        policy (LRU for in-memory, Redis ``maxmemory-policy`` for
        Redis). ``ttl_seconds <= 0`` is a no-op (write-but-immediately-
        expired); adapters should accept it silently.
        """

    async def invalidate(self, key: str) -> None:
        """Drop ``key`` from the cache. Idempotent — missing key is not an error."""
