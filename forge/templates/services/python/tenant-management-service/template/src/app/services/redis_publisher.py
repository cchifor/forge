# src/app/services/redis_publisher.py
"""
Publishes tenant routing configs to Redis for gatekeeper consumption.

The gatekeeper reads ``tenant-route:{hostname}`` keys to resolve
per-tenant OIDC configuration dynamically.
"""

from __future__ import annotations

import json
import logging

import redis.asyncio as redis_async

from app.domain.tenant import TenantRouteConfig

logger = logging.getLogger(__name__)


class RedisPublisher:
    """Writes tenant routing configs to the shared Redis instance."""

    def __init__(self, redis_url: str) -> None:
        self._redis = redis_async.from_url(redis_url, decode_responses=True)

    async def close(self) -> None:
        await self._redis.aclose()

    async def publish_tenant_route(self, hostname: str, config: TenantRouteConfig) -> None:
        """Write a single tenant-route entry."""
        key = f"tenant-route:{hostname}"
        value = json.dumps(config.model_dump())
        await self._redis.set(key, value)
        logger.info("Published tenant route: %s -> %s", key, config.slug)

    async def remove_tenant_route(self, hostname: str, slug: str) -> None:
        """Remove a tenant-route entry (on suspend/delete)."""
        await self._redis.delete(f"tenant-route:{hostname}")
        logger.info("Removed tenant route for %s (%s)", hostname, slug)

    async def publish_tenant_tier(self, tenant_slug: str, rate_limit: int) -> None:
        """Write tenant_tier for backward compatibility with existing gatekeeper rate limiting."""
        await self._redis.set(f"tenant_tier:{tenant_slug}", str(rate_limit))

    async def remove_tenant_tier(self, tenant_slug: str) -> None:
        """Remove tenant_tier entry."""
        await self._redis.delete(f"tenant_tier:{tenant_slug}")

    async def publish_all(self, routes: list[tuple[str, TenantRouteConfig]]) -> int:
        """Bulk write all tenant routes (used at startup for cache warming)."""
        pipe = self._redis.pipeline()
        for hostname, config in routes:
            pipe.set(f"tenant-route:{hostname}", json.dumps(config.model_dump()))
            pipe.set(f"tenant_tier:{config.slug}", str(config.rate_limit))
        await pipe.execute()
        logger.info("Published %d tenant routes to Redis", len(routes))
        return len(routes)
