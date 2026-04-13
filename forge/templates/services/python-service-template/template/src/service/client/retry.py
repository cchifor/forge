"""Retry policy with exponential backoff and jitter."""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable
from typing import TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


class RetryPolicy:
    """Configurable retry with exponential backoff and optional jitter.

    Parameters
    ----------
    max_retries : int
        Maximum number of retry attempts (0 = no retries).
    base_delay : float
        Initial delay in seconds before the first retry.
    max_delay : float
        Cap on the backoff delay.
    jitter : bool
        Add random jitter to prevent thundering herd.
    retryable : callable
        Predicate that receives the exception and returns True if the
        call should be retried.
    """

    def __init__(
        self,
        *,
        max_retries: int = 3,
        base_delay: float = 0.5,
        max_delay: float = 30.0,
        jitter: bool = True,
        retryable: Callable[[Exception], bool] | None = None,
    ):
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.jitter = jitter
        self._retryable = retryable or self._default_retryable

    async def execute(self, fn: Callable[[], Awaitable[T]]) -> T:
        last_exc: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                return await fn()
            except Exception as exc:
                last_exc = exc
                if attempt >= self.max_retries or not self._retryable(exc):
                    raise
                delay = self._compute_delay(attempt)
                logger.warning(
                    "Retry %d/%d after %.2fs: %s",
                    attempt + 1,
                    self.max_retries,
                    delay,
                    exc,
                )
                await asyncio.sleep(delay)
        raise last_exc  # type: ignore[misc]  # unreachable

    def _compute_delay(self, attempt: int) -> float:
        delay = min(self.base_delay * (2**attempt), self.max_delay)
        if self.jitter:
            delay *= 0.5 + random.random()  # noqa: S311
        return delay

    @staticmethod
    def _default_retryable(exc: Exception) -> bool:
        import httpx

        if isinstance(exc, httpx.HTTPStatusError):
            return exc.response.status_code >= 500
        if isinstance(exc, (httpx.ConnectError, httpx.ReadTimeout, httpx.WriteTimeout)):
            return True
        if isinstance(exc, (ConnectionError, TimeoutError)):
            return True
        return False
