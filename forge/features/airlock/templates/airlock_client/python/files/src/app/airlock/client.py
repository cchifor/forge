"""Async Airlock client for managing sandboxes."""

from __future__ import annotations

import os

import httpx

from app.airlock.context import build_propagation_headers
from app.airlock.errors import AirlockError, AirlockNotFoundError, AirlockTimeoutError
from app.airlock.retry import DEFAULT_RETRY_POLICY, RetryPolicy, raise_for_retry
from app.airlock.sandbox import AsyncAirlockSandboxHandle
from app.airlock.types import CreateSandboxParams, SandboxInfo


class AsyncAirlockClient:
    """Async client for the Airlock sandbox orchestrator REST API.

    Example::

        async with AsyncAirlockClient(base_url="http://airlock:5100") as client:
            sandbox = await client.create(CreateSandboxParams(
                app_id="my-sandbox", image="python:3.13-slim"
            ))
            result = await sandbox.exec("echo hello")
            await sandbox.teardown()
    """

    def __init__(
        self,
        base_url: str | None = None,
        token: str | None = None,
        tenant_id: str = "default",
        *,
        retry_policy: RetryPolicy | None = DEFAULT_RETRY_POLICY,
        timeout: float = 120,
    ) -> None:
        resolved_url = (base_url or os.environ.get("AIRLOCK_BASE_URL", "")).rstrip("/")
        if not resolved_url:
            raise ValueError("Airlock base URL required. Pass base_url= or set AIRLOCK_BASE_URL.")
        self._base_url = resolved_url

        resolved_token = token or os.environ.get("AIRLOCK_TOKEN")
        self._headers: dict[str, str] = {"X-Tenant-ID": tenant_id}
        if resolved_token:
            self._headers["Authorization"] = f"Bearer {resolved_token}"
        self._client = httpx.AsyncClient(timeout=timeout)
        # ``None`` opts out of retries entirely — useful for tests that
        # want deterministic single-shot behaviour.
        self._retry = retry_policy

    async def __aenter__(self) -> AsyncAirlockClient:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.aclose()

    def _raise_for_status(self, resp: httpx.Response) -> None:
        if resp.status_code == 404:
            raise AirlockNotFoundError(resp.text)
        if resp.status_code >= 400:
            detail = resp.text
            try:
                detail = resp.json().get("message", resp.text)
            except Exception:
                pass
            raise AirlockError(f"Airlock API error ({resp.status_code}): {detail}")

    async def _request(self, method: str, url: str, **kwargs: object) -> httpx.Response:
        """Issue an HTTP request with retry/backoff for 5xx + transport errors.

        Trace-context headers (``traceparent``/``tracestate`` via OTel,
        plus any ``X-Correlation-ID`` set via ``set_correlation_id``) are
        injected here so every call carries them even when the caller only
        passes a minimal ``headers=`` dict.
        """
        headers = dict(kwargs.pop("headers", None) or {})  # type: ignore[arg-type]
        # Explicit caller-supplied headers win over auto-propagated ones.
        propagated = build_propagation_headers(extra=headers)
        kwargs["headers"] = propagated

        async def _once() -> httpx.Response:
            try:
                resp = await self._client.request(method, url, **kwargs)  # type: ignore[arg-type]
            except httpx.ReadTimeout as exc:
                raise AirlockTimeoutError(f"{method} {url} timed out") from exc
            # Surface retryable status codes as exceptions so the retry
            # policy can catch them; non-retryable codes pass through.
            raise_for_retry(resp)
            return resp

        if self._retry is None:
            return await _once()
        return await self._retry.execute_async(_once)

    async def create(
        self, params: CreateSandboxParams, timeout: int = 120
    ) -> AsyncAirlockSandboxHandle:
        resp = await self._request(
            "POST",
            f"{self._base_url}/api/v1/sandboxes",
            json=params.model_dump(exclude_none=True),
            headers=self._headers,
            timeout=timeout,
        )
        self._raise_for_status(resp)
        data = resp.json()
        return AsyncAirlockSandboxHandle(
            self._client, data["app_id"], self._base_url, self._headers
        )

    async def get(self, app_id: str) -> AsyncAirlockSandboxHandle:
        resp = await self._request(
            "GET",
            f"{self._base_url}/api/v1/sandboxes/{app_id}",
            headers=self._headers,
        )
        self._raise_for_status(resp)
        return AsyncAirlockSandboxHandle(self._client, app_id, self._base_url, self._headers)

    async def delete(self, app_id: str) -> None:
        resp = await self._request(
            "POST",
            f"{self._base_url}/api/v1/sandboxes/{app_id}/teardown",
            headers=self._headers,
        )
        self._raise_for_status(resp)

    async def list_sandboxes(
        self,
        status: str | None = None,
        *,
        skip: int = 0,
        limit: int = 50,
    ) -> list[SandboxInfo]:
        params: dict[str, str] = {"skip": str(skip), "limit": str(limit)}
        if status:
            params["status"] = status
        resp = await self._request(
            "GET",
            f"{self._base_url}/api/v1/sandboxes",
            params=params,
            headers=self._headers,
        )
        self._raise_for_status(resp)
        return [SandboxInfo(**item) for item in resp.json()["items"]]

    async def aclose(self) -> None:
        """Drain the underlying connection pool. Idempotent."""
        await self._client.aclose()

    # Backwards-compatible alias.
    async def close(self) -> None:
        await self.aclose()
