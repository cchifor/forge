"""Resilient async HTTP client for service-to-service (S2S) communication.

Combines ``httpx``, a retry policy, a circuit breaker, and optional OAuth2
client-credentials auth into a single reusable base class. Propagates the
request correlation id (``forge_core.observability.correlation``) and the
caller identity (``forge_core.domain.context``) on every outbound call, so a
downstream service sees the same correlation id and tenant/user context.

This module is self-contained: it bundles its own lightweight in-memory
``CircuitBreaker`` (no extra dependency). That is deliberately distinct from
the ``reliability.circuit_breaker`` option's ``app/core/circuit_breaker.py``
(a ``purgatory``-backed registry for wrapping *arbitrary* calls) — this one
lives *inside* the HTTP client and keys on the target service.

Usage::

    from app.clients.service_client import ServiceClient, ClientCredentialsAuth

    class KnowledgeClient(ServiceClient):
        def __init__(self) -> None:
            super().__init__(
                base_url="http://knowledge:5002",
                service_name="knowledge",
                auth=ClientCredentialsAuth.from_keycloak(
                    server_url="http://keycloak:8080",
                    realm="app",
                    client_id="svc-orders",
                    client_secret=...,
                ),
            )

        async def search(self, query: str) -> list[dict]:
            return await self.get("/api/v1/search", params={"q": query})

Propagated header names default to the values the generated ``tenant_context``
middleware reads (``x-customer-id`` / ``x-user-id`` / ``x-tenant-slug``);
override the ``*_HEADER`` class attributes if your edge uses different names.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from collections.abc import Awaitable, Callable
from enum import StrEnum, auto
from typing import Any, TypeVar

import httpx
from forge_core.domain.context import get_customer_id, get_tenant_slug, get_user_id
from forge_core.observability.correlation import CORRELATION_HEADER, get_correlation_id

logger = logging.getLogger(__name__)

T = TypeVar("T")


# ── Errors ──────────────────────────────────────────────────────────────────


class ServiceCallError(Exception):
    """Raised when a call to an external service fails."""

    def __init__(
        self,
        service: str,
        method: str,
        url: str,
        status_code: int | None = None,
        body: Any = None,
        cause: Exception | None = None,
    ) -> None:
        self.service = service
        self.method = method
        self.url = url
        self.status_code = status_code
        self.body = body
        msg = f"{service}: {method} {url}"
        if status_code:
            msg += f" -> {status_code}"
        super().__init__(msg)
        if cause:
            self.__cause__ = cause


class CircuitOpenError(ServiceCallError):
    """Raised when the circuit breaker is open and the call is rejected."""

    def __init__(self, service: str, retry_after_seconds: float) -> None:
        self.retry_after_seconds = retry_after_seconds
        super().__init__(service=service, method="*", url="*")

    def __str__(self) -> str:
        return (
            f"Circuit breaker open for {self.service}. "
            f"Retry after {self.retry_after_seconds:.0f}s."
        )


# ── Retry policy ──────────────────────────────────────────────────────────


class RetryPolicy:
    """Configurable retry with exponential backoff and optional jitter."""

    def __init__(
        self,
        *,
        max_retries: int = 3,
        base_delay: float = 0.5,
        max_delay: float = 30.0,
        jitter: bool = True,
        retryable: Callable[[Exception], bool] | None = None,
    ) -> None:
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
        assert last_exc is not None  # unreachable: loop always sets or returns
        raise last_exc

    def _compute_delay(self, attempt: int) -> float:
        delay = min(self.base_delay * (2**attempt), self.max_delay)
        if self.jitter:
            delay *= 0.5 + random.random()
        return delay

    @staticmethod
    def _default_retryable(exc: Exception) -> bool:
        if isinstance(exc, httpx.HTTPStatusError):
            return exc.response.status_code >= 500
        if isinstance(exc, (httpx.ConnectError, httpx.ReadTimeout, httpx.WriteTimeout)):
            return True
        if isinstance(exc, (ConnectionError, TimeoutError)):
            return True
        return False


# ── Circuit breaker ─────────────────────────────────────────────────────────


class _State(StrEnum):
    CLOSED = auto()
    OPEN = auto()
    HALF_OPEN = auto()


class CircuitBreaker:
    """In-memory circuit breaker: CLOSED -> OPEN -> HALF_OPEN -> CLOSED."""

    def __init__(
        self,
        failure_threshold: int = 5,
        reset_timeout: float = 30.0,
        half_open_max: int = 1,
    ) -> None:
        self._failure_threshold = failure_threshold
        self._reset_timeout = reset_timeout
        self._half_open_max = half_open_max

        self._state = _State.CLOSED
        self._failure_count = 0
        self._last_failure_time: float = 0.0
        self._half_open_calls = 0

    @property
    def state(self) -> str:
        self._maybe_transition()
        return self._state

    @property
    def is_open(self) -> bool:
        return self.state == _State.OPEN

    @property
    def retry_after(self) -> float:
        if self._state != _State.OPEN:
            return 0.0
        elapsed = time.monotonic() - self._last_failure_time
        return max(0.0, self._reset_timeout - elapsed)

    def allow_request(self) -> bool:
        self._maybe_transition()
        if self._state == _State.CLOSED:
            return True
        if self._state == _State.HALF_OPEN:
            if self._half_open_calls < self._half_open_max:
                self._half_open_calls += 1
                return True
            return False
        return False  # OPEN

    def record_success(self) -> None:
        self._failure_count = 0
        self._half_open_calls = 0
        self._state = _State.CLOSED

    def record_failure(self) -> None:
        self._failure_count += 1
        self._last_failure_time = time.monotonic()
        if self._failure_count >= self._failure_threshold:
            self._state = _State.OPEN

    def _maybe_transition(self) -> None:
        if self._state == _State.OPEN:
            elapsed = time.monotonic() - self._last_failure_time
            if elapsed >= self._reset_timeout:
                self._state = _State.HALF_OPEN
                self._half_open_calls = 0


# ── OAuth2 client-credentials ─────────────────────────────────────────────


class ClientCredentialsAuth:
    """OAuth2 client-credentials token manager with in-memory caching."""

    def __init__(
        self,
        token_url: str,
        client_id: str,
        client_secret: str,
        *,
        scopes: list[str] | None = None,
        refresh_margin: float = 30.0,
    ) -> None:
        self._token_url = token_url
        self._client_id = client_id
        self._client_secret = client_secret
        self._scopes = scopes or []
        self._refresh_margin = refresh_margin

        self._access_token: str | None = None
        self._expires_at: float = 0.0

    @property
    def is_expired(self) -> bool:
        return time.monotonic() >= (self._expires_at - self._refresh_margin)

    async def get_token(self, client: httpx.AsyncClient) -> str:
        if self._access_token and not self.is_expired:
            return self._access_token

        data: dict[str, Any] = {
            "grant_type": "client_credentials",
            "client_id": self._client_id,
            "client_secret": self._client_secret,
        }
        if self._scopes:
            data["scope"] = " ".join(self._scopes)

        response = await client.post(self._token_url, data=data)
        response.raise_for_status()
        payload = response.json()

        self._access_token = payload["access_token"]
        expires_in = payload.get("expires_in", 300)
        self._expires_at = time.monotonic() + expires_in
        logger.debug("Token refreshed, expires in %ds", expires_in)
        return self._access_token

    @classmethod
    def from_keycloak(
        cls,
        server_url: str,
        realm: str,
        client_id: str,
        client_secret: str,
    ) -> ClientCredentialsAuth:
        token_url = f"{server_url.rstrip('/')}/realms/{realm}/protocol/openid-connect/token"
        return cls(token_url=token_url, client_id=client_id, client_secret=client_secret)


# ── Service client ──────────────────────────────────────────────────────────


class ServiceClient:
    """Base class for resilient service-to-service HTTP calls."""

    #: Outbound header names for propagated identity. Override per deployment
    #: if the edge expects different names — these match the generated
    #: ``tenant_context`` middleware on the receiving side.
    CUSTOMER_ID_HEADER = "x-customer-id"
    USER_ID_HEADER = "x-user-id"
    TENANT_SLUG_HEADER = "x-tenant-slug"

    def __init__(
        self,
        base_url: str,
        service_name: str,
        *,
        timeout: float = 30.0,
        auth: ClientCredentialsAuth | None = None,
        retry: RetryPolicy | None = None,
        circuit_breaker: CircuitBreaker | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._service_name = service_name
        self._timeout = timeout
        self._auth = auth
        self._retry = retry or RetryPolicy()
        self._cb = circuit_breaker or CircuitBreaker()
        self._client: httpx.AsyncClient | None = None

    async def start(self) -> None:
        self._client = httpx.AsyncClient(base_url=self._base_url, timeout=self._timeout)

    async def stop(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError(f"{self._service_name}: client not started. Call start() first.")
        return self._client

    # --- Public HTTP verbs ---

    async def get(self, path: str, **kwargs: Any) -> Any:
        return await self._request("GET", path, **kwargs)

    async def post(self, path: str, **kwargs: Any) -> Any:
        return await self._request("POST", path, **kwargs)

    async def put(self, path: str, **kwargs: Any) -> Any:
        return await self._request("PUT", path, **kwargs)

    async def patch(self, path: str, **kwargs: Any) -> Any:
        return await self._request("PATCH", path, **kwargs)

    async def delete(self, path: str, **kwargs: Any) -> Any:
        return await self._request("DELETE", path, **kwargs)

    # --- Internal ---

    def _propagation_headers(self) -> dict[str, str]:
        """Correlation id + caller identity to forward on S2S calls."""
        headers: dict[str, str] = {}
        correlation_id = get_correlation_id()
        if correlation_id:
            headers[CORRELATION_HEADER] = correlation_id
        try:
            customer_id = get_customer_id()
            if customer_id and customer_id != "public":
                headers[self.CUSTOMER_ID_HEADER] = customer_id
        except (ValueError, LookupError):
            pass
        try:
            user_id = get_user_id()
            if user_id and user_id != "anonymous":
                headers[self.USER_ID_HEADER] = user_id
        except (ValueError, LookupError):
            pass
        tenant_slug = get_tenant_slug()
        if tenant_slug:
            headers[self.TENANT_SLUG_HEADER] = tenant_slug
        return headers

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        url = f"{self._base_url}{path}"

        if not self._cb.allow_request():
            raise CircuitOpenError(self._service_name, self._cb.retry_after)

        async def _do_request() -> Any:
            headers = dict(kwargs.pop("headers", {}) or {})
            headers.update(self._propagation_headers())

            if self._auth:
                token = await self._auth.get_token(self.client)
                headers["Authorization"] = f"Bearer {token}"

            response = await self.client.request(method, path, headers=headers, **kwargs)
            response.raise_for_status()
            self._cb.record_success()
            if response.status_code == 204:
                return None
            return response.json()

        try:
            return await self._retry.execute(_do_request)
        except httpx.HTTPStatusError as exc:
            self._cb.record_failure()
            raise ServiceCallError(
                service=self._service_name,
                method=method,
                url=url,
                status_code=exc.response.status_code,
                body=exc.response.text,
                cause=exc,
            ) from exc
        except Exception as exc:
            self._cb.record_failure()
            raise ServiceCallError(
                service=self._service_name, method=method, url=url, cause=exc
            ) from exc
