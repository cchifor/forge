# src/app/gatekeeper/redis.py
"""
Resilient async Redis client with automatic in-memory fallback.

When Redis is unavailable (at startup or during operation), all
operations transparently fall back to an in-memory store.  A background
``asyncio`` task retries the Redis connection with **exponential backoff**.
Once Redis recovers, subsequent operations use the live connection again.

Public API
----------
:func:`init_redis`  — call once at startup (ASGI lifespan).
:func:`close_redis` — call once at shutdown.
:func:`get_redis`   — obtain the active client (``ResilientRedis`` or test stub).
:func:`set_redis`   — inject a replacement client (used in tests).
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import redis.asyncio as redis

from app.gatekeeper.config import get_settings

logger = logging.getLogger(__name__)

# Errors that signal a Redis connectivity problem.
_RECONNECT_ERRORS = (
    redis.ConnectionError,
    redis.TimeoutError,
    ConnectionRefusedError,
    OSError,
)


# ╔═══════════════════════════════════════════════════════════════════════════╗
# ║  In-Memory Store                                                        ║
# ╚═══════════════════════════════════════════════════════════════════════════╝


class InMemoryStore:
    """
    Async in-memory key-value store that implements the Redis API subset
    used by the Gatekeeper (``get``, ``set``, ``delete``, ``incr``,
    ``expire``, ``sadd``, ``smembers``, ``srem``, ``pipeline``).
    """

    def __init__(self) -> None:
        self._data: dict[str, str] = {}
        self._expiry: dict[str, float] = {}
        self._sets: dict[str, set[str]] = {}

    # -- Expiry bookkeeping -----------------------------------------------

    def _evict_if_expired(self, key: str) -> bool:
        """Remove *key* if its TTL has elapsed.  Returns ``True`` if evicted."""
        if key in self._expiry and time.time() > self._expiry[key]:
            self._data.pop(key, None)
            self._expiry.pop(key, None)
            return True
        return False

    # -- String commands --------------------------------------------------

    async def get(self, key: str) -> str | None:
        self._evict_if_expired(key)
        return self._data.get(key)

    async def set(self, key: str, value: str, **kwargs: Any) -> None:  # noqa: A003
        self._data[key] = value

    async def delete(self, *keys: str) -> int:
        count = 0
        for key in keys:
            if self._data.pop(key, None) is not None:
                self._expiry.pop(key, None)
                count += 1
        return count

    async def incr(self, key: str) -> int:
        self._evict_if_expired(key)
        val = int(self._data.get(key, 0)) + 1
        self._data[key] = str(val)
        return val

    async def expire(self, key: str, seconds: int) -> bool:
        if key in self._data:
            self._expiry[key] = time.time() + seconds
            return True
        return False

    # -- Set commands -----------------------------------------------------

    async def sadd(self, key: str, *members: str) -> int:
        if key not in self._sets:
            self._sets[key] = set()
        before = len(self._sets[key])
        self._sets[key].update(members)
        return len(self._sets[key]) - before

    async def smembers(self, key: str) -> set[str]:
        return set(self._sets.get(key, set()))

    async def srem(self, key: str, *members: str) -> int:
        if key not in self._sets:
            return 0
        before = len(self._sets[key])
        self._sets[key] -= set(members)
        return before - len(self._sets[key])

    # -- Pipeline ---------------------------------------------------------

    def pipeline(self, transaction: bool = False) -> InMemoryPipeline:
        return InMemoryPipeline(self)

    # -- Lifecycle --------------------------------------------------------

    async def ping(self) -> bool:
        return True

    async def aclose(self) -> None:
        self._data.clear()
        self._expiry.clear()
        self._sets.clear()


class InMemoryPipeline:
    """Batched command execution against :class:`InMemoryStore`."""

    def __init__(self, store: InMemoryStore) -> None:
        self._store = store
        self._commands: list[tuple[str, tuple[Any, ...]]] = []

    async def __aenter__(self) -> InMemoryPipeline:
        return self

    async def __aexit__(self, *exc: object) -> None:
        pass

    def incr(self, key: str) -> InMemoryPipeline:
        self._commands.append(("incr", (key,)))
        return self

    def expire(self, key: str, seconds: int) -> InMemoryPipeline:
        self._commands.append(("expire", (key, seconds)))
        return self

    async def execute(self) -> list[Any]:
        results: list[Any] = []
        for cmd, args in self._commands:
            method = getattr(self._store, cmd)
            results.append(await method(*args))
        self._commands.clear()
        return results


# ╔═══════════════════════════════════════════════════════════════════════════╗
# ║  Resilient Pipeline                                                     ║
# ╚═══════════════════════════════════════════════════════════════════════════╝


class ResilientPipeline:
    """
    Pipeline proxy that delegates to a live Redis pipeline when available,
    falling back to :class:`InMemoryPipeline` on connection failure.

    Commands are tracked locally so they can be **replayed** on the
    in-memory store if Redis fails mid-pipeline.
    """

    def __init__(self, manager: ResilientRedis, *, transaction: bool = False) -> None:
        self._manager = manager
        self._transaction = transaction
        self._redis_pipe: Any | None = None
        self._memory_pipe: InMemoryPipeline | None = None
        self._commands: list[tuple[str, tuple[Any, ...]]] = []

    async def __aenter__(self) -> ResilientPipeline:
        if self._manager.is_connected:
            try:
                self._redis_pipe = self._manager._redis_client.pipeline(
                    transaction=self._transaction
                )
                await self._redis_pipe.__aenter__()
                return self
            except _RECONNECT_ERRORS as exc:
                self._manager._on_redis_failure(exc)
                self._redis_pipe = None

        self._memory_pipe = self._manager._memory.pipeline(self._transaction)
        await self._memory_pipe.__aenter__()
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._redis_pipe is not None:
            try:
                await self._redis_pipe.__aexit__(*exc)
            except _RECONNECT_ERRORS:
                pass
        if self._memory_pipe is not None:
            await self._memory_pipe.__aexit__(*exc)

    def incr(self, key: str) -> ResilientPipeline:
        self._commands.append(("incr", (key,)))
        if self._redis_pipe is not None:
            self._redis_pipe.incr(key)
        elif self._memory_pipe is not None:
            self._memory_pipe.incr(key)
        return self

    def expire(self, key: str, seconds: int) -> ResilientPipeline:
        self._commands.append(("expire", (key, seconds)))
        if self._redis_pipe is not None:
            self._redis_pipe.expire(key, seconds)
        elif self._memory_pipe is not None:
            self._memory_pipe.expire(key, seconds)
        return self

    async def execute(self) -> list[Any]:
        if self._redis_pipe is not None:
            try:
                return await self._redis_pipe.execute()
            except _RECONNECT_ERRORS as exc:
                self._manager._on_redis_failure(exc)
                # Replay queued commands on the in-memory store.
                mem_pipe = self._manager._memory.pipeline()
                for cmd, args in self._commands:
                    getattr(mem_pipe, cmd)(*args)
                return await mem_pipe.execute()

        if self._memory_pipe is not None:
            return await self._memory_pipe.execute()

        return []


# ╔═══════════════════════════════════════════════════════════════════════════╗
# ║  ResilientRedis                                                         ║
# ╚═══════════════════════════════════════════════════════════════════════════╝


class ResilientRedis:
    """
    Drop-in async Redis client with **automatic in-memory fallback** and
    **exponential-backoff reconnection**.

    Lifecycle
    ---------
    1. :meth:`connect` attempts to reach Redis.  If unreachable, the
       in-memory store is activated and a background reconnect task starts.
    2. Every proxied operation (``get``, ``set``, ``incr``, …) tries
       Redis first.  On connection failure it switches to in-memory and
       triggers a reconnect.
    3. When the reconnect loop succeeds, subsequent operations use Redis
       again transparently.
    4. :meth:`close` cancels the background task and closes Redis.

    Parameters
    ----------
    redis_url:
        Redis connection string (e.g. ``redis://localhost:6379``).
    base_delay:
        Initial retry delay in seconds (default ``1``).
    max_delay:
        Retry delay cap in seconds (default ``60``).
    """

    def __init__(
        self,
        redis_url: str,
        *,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
    ) -> None:
        self._redis_url = redis_url
        self._redis_client: redis.Redis | None = None
        self._memory = InMemoryStore()
        self._using_redis = False
        self._reconnect_task: asyncio.Task[None] | None = None
        self._base_delay = base_delay
        self._max_delay = max_delay
        self._attempt = 0
        self._shutting_down = False

    # -- Public properties ------------------------------------------------

    @property
    def is_connected(self) -> bool:
        """``True`` when a live Redis connection is being used."""
        return self._using_redis

    @property
    def backend_name(self) -> str:
        """``"redis"`` or ``"memory"``."""
        return "redis" if self._using_redis else "memory"

    # -- Lifecycle --------------------------------------------------------

    async def connect(self) -> None:
        """
        Attempt to establish the Redis connection.

        If Redis is unreachable, silently falls back to the in-memory
        store and starts the background reconnect loop.
        """
        try:
            self._redis_client = redis.from_url(self._redis_url, decode_responses=True)
            await self._redis_client.ping()
            self._using_redis = True
            self._attempt = 0
            logger.info("Redis connection established at %s", self._redis_url)
        except _RECONNECT_ERRORS as exc:
            logger.warning(
                "Cannot connect to Redis (%s). Using in-memory fallback.", exc
            )
            self._using_redis = False
            self._schedule_reconnect()

    async def close(self) -> None:
        """Cancel the reconnect task and close all connections."""
        self._shutting_down = True
        if self._reconnect_task and not self._reconnect_task.done():
            self._reconnect_task.cancel()
            try:
                await self._reconnect_task
            except asyncio.CancelledError:
                pass
        if self._redis_client:
            try:
                await self._redis_client.aclose()
            except Exception:
                pass
            self._redis_client = None
        self._using_redis = False
        logger.info("ResilientRedis closed.")

    # -- Reconnection logic -----------------------------------------------

    def _schedule_reconnect(self) -> None:
        """Start the background reconnect loop if not already running."""
        if self._shutting_down:
            return
        if self._reconnect_task is None or self._reconnect_task.done():
            self._reconnect_task = asyncio.create_task(self._reconnect_loop())

    async def _reconnect_loop(self) -> None:
        """Background task: retry Redis with exponential backoff."""
        while not self._shutting_down and not self._using_redis:
            delay = min(self._base_delay * (2**self._attempt), self._max_delay)
            logger.info(
                "Retrying Redis connection in %.1fs (attempt %d)…",
                delay,
                self._attempt + 1,
            )
            await asyncio.sleep(delay)
            if self._shutting_down:
                break
            try:
                if self._redis_client is None:
                    self._redis_client = redis.from_url(
                        self._redis_url, decode_responses=True
                    )
                await self._redis_client.ping()
                self._using_redis = True
                self._attempt = 0
                logger.info("Redis reconnected successfully.")
                return
            except _RECONNECT_ERRORS as exc:
                self._attempt += 1
                logger.warning(
                    "Redis reconnect attempt %d failed: %s", self._attempt, exc
                )

    def _on_redis_failure(self, exc: Exception) -> None:
        """Switch to in-memory and trigger reconnection."""
        if self._using_redis:
            logger.warning(
                "Redis operation failed (%s). Switching to in-memory fallback.",
                exc,
            )
            self._using_redis = False
            self._schedule_reconnect()

    # -- Proxied Redis operations -----------------------------------------

    async def _exec(self, op: str, *args: Any, **kwargs: Any) -> Any:
        """Try *op* on Redis; fall back to in-memory on connection error."""
        if self._using_redis:
            try:
                return await getattr(self._redis_client, op)(*args, **kwargs)
            except _RECONNECT_ERRORS as exc:
                self._on_redis_failure(exc)
        return await getattr(self._memory, op)(*args, **kwargs)

    async def get(self, key: str) -> str | None:
        return await self._exec("get", key)  # type: ignore[return-value]

    async def set(self, key: str, value: str, **kwargs: Any) -> None:  # noqa: A003
        await self._exec("set", key, value, **kwargs)

    async def delete(self, *keys: str) -> int:
        return await self._exec("delete", *keys)  # type: ignore[return-value]

    async def incr(self, key: str) -> int:
        return await self._exec("incr", key)  # type: ignore[return-value]

    async def expire(self, key: str, seconds: int) -> bool:
        return await self._exec("expire", key, seconds)  # type: ignore[return-value]

    async def sadd(self, key: str, *members: str) -> int:
        return await self._exec("sadd", key, *members)  # type: ignore[return-value]

    async def smembers(self, key: str) -> set[str]:
        return await self._exec("smembers", key)  # type: ignore[return-value]

    async def srem(self, key: str, *members: str) -> int:
        return await self._exec("srem", key, *members)  # type: ignore[return-value]

    def pipeline(self, transaction: bool = False) -> ResilientPipeline:
        return ResilientPipeline(self, transaction=transaction)

    async def ping(self) -> bool:
        return await self._exec("ping")  # type: ignore[return-value]

    async def aclose(self) -> None:
        await self.close()


# ╔═══════════════════════════════════════════════════════════════════════════╗
# ║  Module-level API  (backward-compatible)                                ║
# ╚═══════════════════════════════════════════════════════════════════════════╝

_client: ResilientRedis | Any | None = None


async def init_redis() -> ResilientRedis:
    """
    Create (or return) the shared :class:`ResilientRedis` client.

    Called from the ASGI lifespan *startup* phase.  If Redis is
    unreachable the service still starts using in-memory persistence.
    """
    global _client
    if _client is not None:
        return _client  # type: ignore[return-value]

    cfg = get_settings()
    logger.info("Initialising Redis connection to %s …", cfg.redis_url)
    _client = ResilientRedis(cfg.redis_url)
    await _client.connect()
    return _client


async def close_redis() -> None:
    """
    Gracefully close the Redis connection pool and stop background tasks.

    Called from the ASGI lifespan *shutdown* phase.
    """
    global _client
    if _client is not None:
        if isinstance(_client, ResilientRedis):
            await _client.close()
        else:
            await _client.aclose()
        _client = None
        logger.info("Redis connection closed.")


def get_redis() -> ResilientRedis:
    """
    Return the active Redis client.

    Raises
    ------
    RuntimeError
        If called before :func:`init_redis`.
    """
    if _client is None:
        raise RuntimeError("Redis client not initialised — call init_redis() first")
    return _client  # type: ignore[return-value]


def set_redis(client: Any) -> None:
    """
    Override the module-level Redis client.

    Accepts a :class:`ResilientRedis`, a ``fakeredis`` instance (used in
    tests), or ``None`` to clear.
    """
    global _client
    _client = client
