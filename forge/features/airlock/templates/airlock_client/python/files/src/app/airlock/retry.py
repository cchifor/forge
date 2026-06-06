"""Retry policy for the Airlock client.

Retries on 502/503/504 plus transport errors; does NOT retry other 4xx
(retrying a 404 just wastes time). Exponential backoff with jitter.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from collections.abc import Awaitable, Callable
from typing import TypeVar

import httpx

logger = logging.getLogger(__name__)

T = TypeVar("T")


class RetryPolicy:
    def __init__(
        self,
        *,
        max_retries: int = 3,
        base_delay: float = 0.5,
        max_delay: float = 30.0,
        jitter: bool = True,
    ) -> None:
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.jitter = jitter

    @staticmethod
    def retryable(exc: Exception) -> bool:
        if isinstance(exc, httpx.HTTPStatusError):
            return exc.response.status_code in (502, 503, 504)
        if isinstance(exc, (httpx.ConnectError, httpx.ReadTimeout, httpx.WriteTimeout)):
            return True
        if isinstance(exc, (ConnectionError, TimeoutError)):
            return True
        return False

    async def execute_async(self, fn: Callable[[], Awaitable[T]]) -> T:
        last_exc: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                return await fn()
            except Exception as exc:
                last_exc = exc
                if attempt >= self.max_retries or not self.retryable(exc):
                    raise
                delay = self._delay(attempt)
                logger.warning(
                    "airlock retry %d/%d after %.2fs: %s",
                    attempt + 1,
                    self.max_retries,
                    delay,
                    exc,
                )
                await asyncio.sleep(delay)
        assert last_exc is not None  # unreachable: loop returns on success or re-raises
        raise last_exc

    def execute_sync(self, fn: Callable[[], T]) -> T:
        last_exc: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                return fn()
            except Exception as exc:
                last_exc = exc
                if attempt >= self.max_retries or not self.retryable(exc):
                    raise
                delay = self._delay(attempt)
                logger.warning(
                    "airlock retry %d/%d after %.2fs: %s",
                    attempt + 1,
                    self.max_retries,
                    delay,
                    exc,
                )
                time.sleep(delay)
        assert last_exc is not None  # unreachable: loop returns on success or re-raises
        raise last_exc

    def _delay(self, attempt: int) -> float:
        delay = min(self.base_delay * (2**attempt), self.max_delay)
        if self.jitter:
            delay *= 0.5 + random.random()  # noqa: S311
        return delay


DEFAULT_RETRY_POLICY = RetryPolicy()


def raise_for_retry(response: httpx.Response) -> None:
    """Raise ``HTTPStatusError`` if the response is retryable (5xx)."""
    if response.status_code in (502, 503, 504):
        response.raise_for_status()
