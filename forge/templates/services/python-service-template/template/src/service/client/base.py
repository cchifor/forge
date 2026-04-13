"""Resilient async HTTP client for service-to-service communication.

Combines httpx, retry policy, circuit breaker, and optional OAuth2 auth
into a single reusable base class.

Usage::

    class KnowledgeClient(ServiceClient):
        def __init__(self):
            super().__init__(
                base_url="http://knowledge:5002",
                service_name="knowledge",
            )

        async def search(self, query: str) -> list[dict]:
            return await self.get("/api/v1/search", params={"q": query})
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from service.client.auth import ClientCredentialsAuth
from service.client.circuit_breaker import CircuitBreaker
from service.client.errors import CircuitOpenError, ServiceCallError
from service.client.retry import RetryPolicy
from service.observability.correlation import CORRELATION_HEADER, get_correlation_id

logger = logging.getLogger(__name__)


class ServiceClient:
    """Base class for resilient service-to-service HTTP calls.

    Parameters
    ----------
    base_url : str
        Root URL of the target service (e.g. ``http://knowledge:5002``).
    service_name : str
        Human-readable name for logging and circuit breaker keying.
    timeout : float
        Default request timeout in seconds.
    auth : ClientCredentialsAuth | None
        Optional OAuth2 client-credentials manager.
    retry : RetryPolicy | None
        Retry configuration. Defaults to 3 retries with exponential backoff.
    circuit_breaker : CircuitBreaker | None
        Circuit breaker configuration. Defaults to 5-failure threshold.
    """

    def __init__(
        self,
        base_url: str,
        service_name: str,
        *,
        timeout: float = 30.0,
        auth: ClientCredentialsAuth | None = None,
        retry: RetryPolicy | None = None,
        circuit_breaker: CircuitBreaker | None = None,
    ):
        self._base_url = base_url.rstrip("/")
        self._service_name = service_name
        self._timeout = timeout
        self._auth = auth
        self._retry = retry or RetryPolicy()
        self._cb = circuit_breaker or CircuitBreaker()
        self._client: httpx.AsyncClient | None = None

    async def start(self) -> None:
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=self._timeout,
        )

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

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        url = f"{self._base_url}{path}"

        if not self._cb.allow_request():
            raise CircuitOpenError(self._service_name, self._cb.retry_after)

        async def _do_request() -> Any:
            headers = kwargs.pop("headers", {})

            # Propagate correlation ID
            correlation_id = get_correlation_id()
            if correlation_id:
                headers[CORRELATION_HEADER] = correlation_id

            # Propagate tenant context for S2S calls
            from service.core.context import get_customer_id, get_user_id  # noqa: E402
            try:
                customer_id = get_customer_id()
                if customer_id and customer_id != "public":
                    headers["x-customer-id"] = customer_id
            except (ValueError, LookupError):
                pass
            try:
                user_id = get_user_id()
                if user_id and user_id != "anonymous":
                    headers["x-gatekeeper-user-id"] = user_id
            except (ValueError, LookupError):
                pass

            # Attach auth token
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
                service=self._service_name,
                method=method,
                url=url,
                cause=exc,
            ) from exc
