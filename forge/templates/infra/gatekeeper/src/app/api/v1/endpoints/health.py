from __future__ import annotations

import logging
import time
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from app.gatekeeper.redis import ResilientRedis, get_redis

logger = logging.getLogger(__name__)

router = APIRouter()


# ── Response models ─────────────────────────────────────────────────────────


class ComponentHealth(BaseModel):
    """Health status of an individual component."""

    status: str  # "up" | "degraded" | "down"
    backend: str | None = None
    latency_ms: float | None = None
    detail: str | None = None


class LivenessResponse(BaseModel):
    status: str
    detail: str


class ReadinessResponse(BaseModel):
    status: str  # "up" | "degraded"
    components: dict[str, ComponentHealth]


# ── Liveness ────────────────────────────────────────────────────────────────


@router.get("/live", response_model=LivenessResponse)
async def liveness_probe() -> LivenessResponse:
    """
    Kubernetes **liveness** probe.

    Always returns ``200 OK`` if the Python process is alive.
    Kubernetes should restart the pod only if this endpoint stops
    responding entirely.
    """
    return LivenessResponse(status="up", detail="Service is running")


# ── Readiness ───────────────────────────────────────────────────────────────


@router.get("/ready", response_model=ReadinessResponse)
async def readiness_probe() -> ReadinessResponse:
    """
    Kubernetes **readiness** probe.

    Checks the Redis backend and reports the overall service health:

    * **up** — Redis is connected and responding.
    * **degraded** — Redis is unreachable; the service is operating on
      an in-memory fallback.  Rate limiting is per-node only, and
      API-key lookups are unavailable until Redis reconnects.

    The endpoint always returns ``200 OK`` so the pod keeps receiving
    traffic even in degraded mode (Gatekeeper sits on the critical
    path for all platform traffic).
    """
    redis_health = await _check_redis()

    overall = "up" if redis_health.status == "up" else "degraded"

    return ReadinessResponse(
        status=overall,
        components={"redis": redis_health},
    )


async def _check_redis() -> ComponentHealth:
    """Probe the Redis connection and return its health."""
    try:
        client = get_redis()
    except RuntimeError:
        return ComponentHealth(
            status="down",
            backend="none",
            detail="Redis client not initialised",
        )

    generic_client: Any = client

    # Determine backend type
    if isinstance(client, ResilientRedis):
        if not client.is_connected:
            return ComponentHealth(
                status="degraded",
                backend="memory",
                detail="Redis unreachable — using in-memory fallback with reconnect backoff",
            )
        # Redis is nominally connected — verify with a ping
        try:
            t0 = time.monotonic()
            await client.ping()
            latency_ms = round((time.monotonic() - t0) * 1000, 2)
            return ComponentHealth(
                status="up",
                backend="redis",
                latency_ms=latency_ms,
            )
        except Exception as exc:
            logger.warning("Redis ping failed during readiness check: %s", exc)
            return ComponentHealth(
                status="degraded",
                backend="memory",
                detail=f"Redis ping failed: {exc}",
            )
    else:
        # Test / fakeredis client — treat as healthy
        try:
            t0 = time.monotonic()
            await generic_client.ping()
            latency_ms = round((time.monotonic() - t0) * 1000, 2)
            return ComponentHealth(
                status="up",
                backend="redis",
                latency_ms=latency_ms,
            )
        except Exception as exc:
            return ComponentHealth(
                status="down",
                backend="unknown",
                detail=str(exc),
            )
