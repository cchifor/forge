"""Redis-backed JWT ``jti`` denylist.

Short-lived access tokens (≤15 min) bound the cardinality of this set —
even at 10k revocations/day the working set stays trivially small.

Failure mode is intentional: a Redis outage causes :meth:`is_revoked` to
**fail open** (return ``False``) with a logged warning. Failing closed
would flatline every service whenever Redis blipped, which is a worse
trade-off than briefly accepting a token whose revocation we cannot
verify — natural ``exp`` expiry caps the blast radius. Operators get
alerted via the warning log + a metric increment so the outage is
visible.

The producer (Gatekeeper on logout / forced revocation / tenant
suspension) calls :meth:`add` with ``ttl_seconds = remaining_exp`` so the
key cleans itself up at natural token expiry.
"""

from __future__ import annotations

import logging

import redis.asyncio as aioredis
from redis.exceptions import RedisError

_log = logging.getLogger(__name__)


class RevocationStore:
    """Redis-backed ``jti`` denylist."""

    DEFAULT_KEY_PREFIX = "revoked:jti"

    def __init__(
        self,
        client: aioredis.Redis,
        *,
        key_prefix: str = DEFAULT_KEY_PREFIX,
    ) -> None:
        if not key_prefix:
            raise ValueError("key_prefix must be non-empty")
        self._client = client
        self._key_prefix = key_prefix

    def _key(self, jti: str) -> str:
        return f"{self._key_prefix}:{jti}"

    async def add(self, jti: str, ttl_seconds: int) -> None:
        """Mark ``jti`` as revoked for at most ``ttl_seconds``.

        Idempotent — adding the same jti twice extends or replaces the TTL.
        Non-positive TTLs are no-ops; the token is already expired by the
        time we'd be asked about it.
        """
        if not jti:
            raise ValueError("jti must be non-empty")
        if ttl_seconds <= 0:
            return
        try:
            await self._client.set(self._key(jti), b"1", ex=ttl_seconds)
        except RedisError as exc:
            # Producer-side failure to record a revocation is more serious
            # than consumer-side failure to look one up: the operator who
            # asked us to revoke needs to know it didn't take.
            _log.error(
                "revocation_add_failed",
                extra={"jti": jti, "ttl_seconds": ttl_seconds, "error": str(exc)},
            )
            raise

    async def is_revoked(self, jti: str) -> bool:
        """Return ``True`` if ``jti`` is on the denylist.

        Empty/missing jti returns ``False`` — :class:`platform_auth.AuthGuard`
        rejects tokens without a ``jti`` claim before reaching this check.

        On Redis failure, returns ``False`` (fail open) and logs a warning;
        see module docstring for rationale.
        """
        if not jti:
            return False
        try:
            return bool(await self._client.exists(self._key(jti)))
        except RedisError as exc:
            _log.warning(
                "revocation_check_failed_fail_open",
                extra={"jti": jti, "error": str(exc)},
            )
            return False

    async def aclose(self) -> None:
        """Close the underlying Redis client.

        Provided for symmetry with other SDK components; in practice the
        Redis client is shared across the application and closed by the
        application's lifecycle.
        """
        await self._client.aclose()


__all__ = ["RevocationStore"]
