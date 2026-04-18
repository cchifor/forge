"""Supplemental readiness checks for downstream services.

Each check returns a tuple of (is_up, latency_ms, error_message). They are
intentionally best-effort — a misconfigured URL or missing optional dep
produces a DOWN result rather than raising. Use from a route handler or
wire into :class:`app.services.health_service.HealthService`.
"""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class CheckResult:
    up: bool
    latency_ms: float
    error: str | None = None

    def as_dict(self) -> dict:
        return {
            "status": "up" if self.up else "down",
            "latency_ms": round(self.latency_ms, 2),
            "error": self.error,
        }


async def check_redis(url: str | None = None, timeout_s: float = 2.0) -> CheckResult:
    """Ping a Redis server. Requires `redis.asyncio` if used; gracefully
    degrades to DOWN if the dep is missing."""
    url = url or os.environ.get("REDIS_URL", "redis://redis:6379/0")
    start = time.perf_counter()
    try:
        from redis.asyncio import from_url  # type: ignore
    except ImportError:
        return CheckResult(
            up=False,
            latency_ms=0.0,
            error="redis.asyncio not installed (pip install redis)",
        )
    try:
        client = from_url(url, socket_connect_timeout=timeout_s)
        try:
            await asyncio.wait_for(client.ping(), timeout=timeout_s)
            return CheckResult(up=True, latency_ms=(time.perf_counter() - start) * 1000)
        finally:
            await client.aclose()
    except Exception as e:  # noqa: BLE001
        return CheckResult(
            up=False, latency_ms=(time.perf_counter() - start) * 1000, error=str(e)
        )


async def check_keycloak(url: str | None = None, timeout_s: float = 3.0) -> CheckResult:
    """GET ${url}/health/ready on the Keycloak management port. Falls back to
    the standard http://keycloak:9000 if no url is provided."""
    url = url or os.environ.get("KEYCLOAK_HEALTH_URL", "http://keycloak:9000/health/ready")
    start = time.perf_counter()
    try:
        import httpx  # type: ignore
    except ImportError:
        return CheckResult(up=False, latency_ms=0.0, error="httpx not installed")
    try:
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            resp = await client.get(url)
        return CheckResult(
            up=resp.status_code == 200,
            latency_ms=(time.perf_counter() - start) * 1000,
            error=None if resp.status_code == 200 else f"http {resp.status_code}",
        )
    except Exception as e:  # noqa: BLE001
        return CheckResult(
            up=False, latency_ms=(time.perf_counter() - start) * 1000, error=str(e)
        )
