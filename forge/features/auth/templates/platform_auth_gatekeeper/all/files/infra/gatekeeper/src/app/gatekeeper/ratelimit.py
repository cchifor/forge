# src/app/gatekeeper/ratelimit.py
"""
Distributed, tenant-level rate limiting backed by Redis.

Uses the **atomic fixed-window counter** algorithm:
- Time is divided into 60-second windows.
- A Redis key ``ratelimit:<tenant>:<window>`` is incremented atomically
  via a pipeline (INCR + EXPIRE in one round-trip).
- When the counter exceeds the tenant's quota the Gatekeeper returns
  HTTP 429 directly, so the request never reaches the backend.

Standard ``X-RateLimit-*`` headers are injected into every response so
clients can self-throttle.
"""

from __future__ import annotations

import logging
import time

from fastapi import HTTPException

from app.gatekeeper.redis import get_redis

logger = logging.getLogger(__name__)


async def get_tenant_quota(tenant_id: str, default: int) -> int:
    """
    Fetch the per-minute quota for *tenant_id* from Redis.

    Falls back to *default* if no custom tier is stored.  Tenant tiers
    are published to ``tenant_tier:<tenant_id>`` by the billing service
    on plan changes.
    """
    r = get_redis()
    raw = await r.get(f"tenant_tier:{tenant_id}")
    if raw is not None:
        try:
            return int(raw)
        except (ValueError, TypeError):
            pass
    return default


async def enforce_rate_limit(
    tenant_id: str,
    limit_per_minute: int,
) -> dict[str, str]:
    """
    Atomically increment the tenant's request counter for the current
    minute and enforce the quota.

    Returns
    -------
    dict[str, str]
        Rate-limit headers to attach to the response.

    Raises
    ------
    HTTPException(429)
        When the tenant has exceeded their quota.
    """
    r = get_redis()

    current_time = int(time.time())
    window_minute = current_time // 60
    redis_key = f"ratelimit:{tenant_id}:{window_minute}"

    # Atomic pipeline: INCR + EXPIRE in a single round-trip
    async with r.pipeline(transaction=True) as pipe:
        pipe.incr(redis_key)
        pipe.expire(redis_key, 120)  # auto-cleanup after 2 minutes
        results = await pipe.execute()

    current_count: int = results[0]

    remaining = max(0, limit_per_minute - current_count)
    reset_time = (window_minute + 1) * 60

    headers = {
        "X-RateLimit-Limit": str(limit_per_minute),
        "X-RateLimit-Remaining": str(remaining),
        "X-RateLimit-Reset": str(reset_time),
    }

    if current_count > limit_per_minute:
        logger.warning(
            "Rate limit exceeded for tenant=%s (%d/%d)",
            tenant_id,
            current_count,
            limit_per_minute,
        )
        raise HTTPException(
            status_code=429,
            detail="Too Many Requests. Tenant quota exceeded.",
            headers=headers,
        )

    return headers
