"""In-memory per-tenant/per-IP token-bucket rate limiter."""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from fastapi import Request, Response, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)


@dataclass
class _Bucket:
    tokens: float
    last_refill: float = field(default_factory=time.monotonic)


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app,
        *,
        requests_per_minute: int = 120,
        burst: int | None = None,
        skip_paths: list[str] | None = None,
    ):
        super().__init__(app)
        self._rate = requests_per_minute / 60.0
        self._capacity = float(burst or requests_per_minute)
        self._buckets: dict[str, _Bucket] = defaultdict(lambda: _Bucket(tokens=self._capacity))
        self._skip_paths = set(skip_paths or [])

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if any(request.url.path.startswith(p) for p in self._skip_paths):
            return await call_next(request)

        key = self._resolve_key(request)
        bucket = self._buckets[key]
        now = time.monotonic()

        elapsed = now - bucket.last_refill
        bucket.tokens = min(self._capacity, bucket.tokens + elapsed * self._rate)
        bucket.last_refill = now

        if bucket.tokens < 1.0:
            retry_after = int((1.0 - bucket.tokens) / self._rate) + 1
            logger.warning("Rate limit exceeded for key=%s", key)
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={"detail": "Rate limit exceeded. Please slow down."},
                headers={"Retry-After": str(retry_after)},
            )

        bucket.tokens -= 1.0
        return await call_next(request)

    @staticmethod
    def _resolve_key(request: Request) -> str:
        user = getattr(request.state, "user", None)
        if user is not None:
            customer_id = getattr(user, "customer_id", None)
            if customer_id:
                return f"tenant:{customer_id}"
        if request.client:
            return f"ip:{request.client.host}"
        return "anonymous"
