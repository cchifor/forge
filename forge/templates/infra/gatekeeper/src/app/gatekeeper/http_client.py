# src/app/gatekeeper/http_client.py
"""
Shared ``httpx.AsyncClient`` for outbound HTTP calls (Keycloak OIDC, JWKS).

Maintains a single connection pool across the application lifetime so
that repeated calls reuse TCP connections instead of opening a fresh
socket (and TLS handshake) for every request.

Public API
----------
:func:`init_http_client`  — call once at startup (ASGI lifespan).
:func:`close_http_client` — call once at shutdown.
:func:`get_http_client`   — obtain the active client.
:func:`set_http_client`   — inject a replacement (used in tests).
"""

from __future__ import annotations

import asyncio
import functools
import logging
from collections.abc import Callable, Coroutine
from typing import Any, TypeVar

import httpx

T = TypeVar("T")

logger = logging.getLogger(__name__)

_client: httpx.AsyncClient | None = None


async def init_http_client(
    *,
    timeout: float = 10.0,
    max_connections: int = 20,
    max_keepalive_connections: int = 10,
) -> httpx.AsyncClient:
    """
    Create (or return) the shared :class:`httpx.AsyncClient`.

    Called from the ASGI lifespan *startup* phase.
    """
    global _client
    if _client is not None:
        return _client

    _client = httpx.AsyncClient(
        timeout=timeout,
        limits=httpx.Limits(
            max_connections=max_connections,
            max_keepalive_connections=max_keepalive_connections,
        ),
    )
    logger.info(
        "HTTP client initialised (max_connections=%d, keepalive=%d)",
        max_connections,
        max_keepalive_connections,
    )
    return _client


async def close_http_client() -> None:
    """
    Close the shared HTTP client and release pooled connections.

    Called from the ASGI lifespan *shutdown* phase.
    """
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
        logger.info("HTTP client closed.")


def get_http_client() -> httpx.AsyncClient:
    """
    Return the active HTTP client.

    Raises
    ------
    RuntimeError
        If called before :func:`init_http_client`.
    """
    if _client is None:
        raise RuntimeError(
            "HTTP client not initialised — call init_http_client() first"
        )
    return _client


def set_http_client(client: httpx.AsyncClient | None) -> None:
    """
    Override the module-level HTTP client (used in tests).
    """
    global _client
    _client = client


# ── Retry decorator ───────────────────────────────────────────────────────

# Transient errors worth retrying (connection-level).
_RETRYABLE_ERRORS = (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout)

# HTTP status codes that indicate a transient upstream issue.
_RETRYABLE_STATUS_CODES = frozenset({502, 503, 504})


def with_retry(
    max_attempts: int = 3,
    backoff_base: float = 0.1,
) -> Callable[
    [Callable[..., Coroutine[Any, Any, T]]],
    Callable[..., Coroutine[Any, Any, T]],
]:
    """
    Retry an ``async`` function on transient HTTP / connection errors.

    Retries on :data:`_RETRYABLE_ERRORS` and on HTTP responses with
    status codes in :data:`_RETRYABLE_STATUS_CODES`.  Client errors
    (4xx) are **not** retried.

    Parameters
    ----------
    max_attempts:
        Total attempts (including the first).  Default ``3``.
    backoff_base:
        Initial delay in seconds, doubled on each retry.  Default ``0.1``.
    """

    def decorator(
        fn: Callable[..., Coroutine[Any, Any, T]],
    ) -> Callable[..., Coroutine[Any, Any, T]]:
        @functools.wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> T:
            last_exc: Exception | None = None
            for attempt in range(max_attempts):
                try:
                    return await fn(*args, **kwargs)
                except _RETRYABLE_ERRORS as exc:
                    last_exc = exc
                except httpx.HTTPStatusError as exc:
                    if exc.response.status_code not in _RETRYABLE_STATUS_CODES:
                        raise  # 4xx — not retryable
                    last_exc = exc

                if attempt < max_attempts - 1:
                    delay = backoff_base * (2**attempt)
                    logger.warning(
                        "Retrying %s (attempt %d/%d) after %.2fs: %s",
                        fn.__name__,
                        attempt + 2,
                        max_attempts,
                        delay,
                        last_exc,
                    )
                    await asyncio.sleep(delay)

            raise last_exc  # type: ignore[misc]

        return wrapper

    return decorator
