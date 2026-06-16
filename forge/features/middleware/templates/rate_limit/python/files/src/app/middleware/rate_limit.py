"""In-memory per-tenant/per-IP token-bucket rate limiter."""

from __future__ import annotations

import ipaddress
import logging
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from fastapi import Request, Response, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)


def is_trusted_peer(ip: str) -> bool:
    """Return ``True`` when ``ip`` is an in-cluster / proxy peer we trust to
    have set ``X-Forwarded-For`` honestly.

    Heuristic: trust loopback, RFC1918 private, and link-local addresses — the
    documented Traefik topology terminates external traffic at an in-cluster
    reverse proxy whose peer address is private. A public transport peer means
    the request reached us directly (or via an XFF-appending hop), so a
    client-supplied XFF can't be trusted. A stricter explicit CIDR allowlist
    can be layered on top of this later.
    """
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return addr.is_private or addr.is_loopback or addr.is_link_local

# Cap on the number of distinct client buckets kept in memory. Once exceeded,
# the least-recently-used bucket is evicted. Without this, a flood of unique
# clients (each a fresh X-Forwarded-For address) would grow the map without
# bound — a memory-exhaustion vector.
_MAX_BUCKETS = 4096


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
        # LRU-ordered so we can evict the least-recently-used idle bucket once
        # the map is full, keeping the limiter's memory bounded.
        self._buckets: OrderedDict[str, _Bucket] = OrderedDict()
        self._skip_paths = set(skip_paths or [])

    def _get_bucket(self, key: str) -> _Bucket:
        bucket = self._buckets.get(key)
        if bucket is None:
            # Evict the oldest (least-recently-used) bucket(s) before inserting
            # so the map can never exceed the cap.
            while len(self._buckets) >= _MAX_BUCKETS:
                self._buckets.popitem(last=False)
            bucket = _Bucket(tokens=self._capacity)
            self._buckets[key] = bucket
        else:
            # Mark as most-recently-used.
            self._buckets.move_to_end(key)
        return bucket

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if any(request.url.path.startswith(p) for p in self._skip_paths):
            return await call_next(request)

        key = self._resolve_key(request)
        bucket = self._get_bucket(key)
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
        # Behind a reverse proxy / load balancer, ``request.client.host`` is the
        # proxy's address, shared by every anonymous client — keying on it would
        # collapse them all into one bucket. Prefer the left-most (originating)
        # address from X-Forwarded-For when present.
        #
        # SECURITY: only trust X-Forwarded-For when the immediate transport peer
        # is itself a trusted in-cluster proxy (private / loopback / link-local
        # — the documented Traefik topology). If the peer is a public address
        # the request reached us directly (internet-facing) or via an
        # XFF-appending hop, and a client-supplied XFF could be used to spoof /
        # evade its rate-limit bucket — so we ignore it and key on the peer.
        peer_host = request.client.host if request.client else None
        if peer_host and is_trusted_peer(peer_host):
            forwarded = request.headers.get("x-forwarded-for")
            if forwarded:
                client_ip = forwarded.split(",", 1)[0].strip()
                if client_ip:
                    return f"ip:{client_ip}"
        if peer_host:
            return f"ip:{peer_host}"
        return "anonymous"
