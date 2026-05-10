# src/app/gatekeeper/internal_token_cache.py
"""Per-Keycloak-jti cache for gatekeeper-minted internal JWTs.

Without caching, gatekeeper would sign a fresh ES256 JWT on every
authenticated request that flows through the Traefik ForwardAuth path —
once per HTTP call from any browser tab. With caching keyed on the
Keycloak access token's ``jti``, gatekeeper signs once per access-token
issuance (typically once per 5-minute Keycloak window) and reuses the
result for every subsequent request that arrives during that window.

Steady state: one Keycloak access token → one minted internal JWT →
served from cache for hundreds of requests. Cache hit rate target ≥99%.

Defense in depth: every cache hit is **verified** against the KeyRing's
JWKS before being returned. A bad actor who can write to Redis cannot
inject an arbitrary token because their value will fail signature
verification on read. The verify-on-read cost (~100 µs) is the price
for not having to trust the cache.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import jwt as pyjwt

from app.gatekeeper.helpers import JWTPayload
from app.gatekeeper.internal_token import AuthMethod, mint_internal_token
from app.gatekeeper.key_store import KeyRing

logger = logging.getLogger(__name__)


CACHE_KEY_PREFIX = "gk:internal_jwt"


class InternalTokenCache:
    """Cache + mint orchestrator.

    Public API is :meth:`get_or_mint` which encapsulates the full
    "look up cache, verify hit, fall through to mint, cache result" flow.
    """

    def __init__(
        self,
        *,
        redis: Any,
        key_ring: KeyRing,
        issuer: str,
        audience: str,
        ttl_seconds: int,
        key_prefix: str = CACHE_KEY_PREFIX,
    ) -> None:
        self._redis = redis
        self._key_ring = key_ring
        self._issuer = issuer
        self._audience = audience
        self._ttl_seconds = ttl_seconds
        self._key_prefix = key_prefix

    # ── Cache key helpers ──────────────────────────────────────────────

    def _cache_key(self, keycloak_jti: str) -> str:
        return f"{self._key_prefix}:{keycloak_jti}"

    # ── Verification ───────────────────────────────────────────────────

    def _verify_cached_token(self, token: str) -> dict[str, Any] | None:
        """Decode *token* against the current KeyRing JWKS.

        Returns the decoded payload on success, ``None`` on any failure
        (bad signature, expired, missing kid, audience mismatch).
        Failures are silent — the caller treats them as cache misses.
        """
        try:
            header = pyjwt.get_unverified_header(token)
            kid = header.get("kid")
            if not kid:
                return None
            jwks = self._key_ring.public_jwks()
            matching = next(
                (jwk for jwk in jwks["keys"] if jwk["kid"] == kid),
                None,
            )
            if matching is None:
                # The signing key has been retired and dropped from the
                # ring. Treat the cached token as stale.
                return None
            public_key = pyjwt.algorithms.ECAlgorithm.from_jwk(matching)
            return pyjwt.decode(
                token,
                public_key,
                algorithms=["ES256"],
                audience=self._audience,
            )
        except Exception as exc:  # noqa: BLE001 — any verification fail = miss
            logger.warning(
                "internal_token_cache.verify_failed",
                extra={"reason": type(exc).__name__, "detail": str(exc)},
            )
            return None

    # ── Public API ─────────────────────────────────────────────────────

    async def get_or_mint(
        self,
        *,
        keycloak_payload: JWTPayload | dict[str, Any],
        auth_method: AuthMethod = "cookie",
    ) -> tuple[str, int]:
        """Return ``(token, exp_unix)``: cached if valid, else freshly minted.

        When ``keycloak_payload`` lacks a ``jti``, caching is skipped and
        a fresh token is minted on every call. (Production Keycloak
        tokens always carry ``jti``; this branch exists for defensive
        synthetic payloads.)
        """
        kc_jti = keycloak_payload.get("jti")
        if not kc_jti:
            return self._mint_fresh(keycloak_payload, auth_method)

        cache_key = self._cache_key(str(kc_jti))
        try:
            cached = await self._redis.get(cache_key)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "internal_token_cache.redis_get_failed",
                extra={"reason": type(exc).__name__, "detail": str(exc)},
            )
            cached = None

        if cached:
            decoded = self._verify_cached_token(cached)
            if decoded is not None:
                logger.debug(
                    "internal_token_cache.hit",
                    extra={"keycloak_jti": kc_jti, "exp": decoded.get("exp")},
                )
                return cached, int(decoded["exp"])
            # Hit but verification failed — likely stale-key or poisoning
            # attempt. Fall through to mint a fresh one and overwrite.
            logger.info(
                "internal_token_cache.invalid_cached_token",
                extra={"keycloak_jti": kc_jti},
            )

        # Mint fresh and cache.
        token, exp = self._mint_fresh(keycloak_payload, auth_method)
        ttl = max(1, exp - int(time.time()))
        try:
            await self._redis.set(cache_key, token, ex=ttl)
        except Exception as exc:  # noqa: BLE001
            # If Redis is down we still serve the freshly-minted token;
            # the next call will mint again. Acceptable degradation.
            logger.warning(
                "internal_token_cache.redis_set_failed",
                extra={"reason": type(exc).__name__, "detail": str(exc)},
            )
        return token, exp

    async def invalidate(self, keycloak_jti: str) -> None:
        """Remove a cached entry. Used by future back-channel logout flow."""
        try:
            await self._redis.delete(self._cache_key(keycloak_jti))
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "internal_token_cache.redis_delete_failed",
                extra={"reason": type(exc).__name__, "detail": str(exc)},
            )

    async def evict_for_sub(self, sub: str) -> int:
        """Best-effort eviction of every cached internal JWT minted for ``sub``.

        Called from ``/logout`` so a user who just signed out cannot
        replay an internal JWT for the cache TTL window (default 5 min).
        Implementation: ``SCAN`` over ``gk:internal_jwt:*``, decode each
        cached token without signature verification, and ``DEL`` rows
        whose payload's ``sub`` matches.

        Returns the number of rows deleted. ``0`` on Redis failure or
        when nothing matched. Failures are logged at WARNING and
        swallowed — eviction is best-effort; the worst case is the
        documented 5-minute replay window.
        """
        if not sub:
            return 0
        deleted = 0
        pattern = f"{self._key_prefix}:*"
        try:
            scan_iter = self._redis.scan_iter(match=pattern, count=200)
            async for raw_key in scan_iter:
                cache_key = (
                    raw_key.decode("utf-8")
                    if isinstance(raw_key, bytes)
                    else raw_key
                )
                try:
                    token = await self._redis.get(cache_key)
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "internal_token_cache.evict_get_failed",
                        extra={
                            "key": cache_key,
                            "reason": type(exc).__name__,
                            "detail": str(exc),
                        },
                    )
                    continue
                if not token:
                    continue
                try:
                    payload = pyjwt.decode(
                        token,
                        options={
                            "verify_signature": False,
                            "verify_aud": False,
                            "verify_exp": False,
                        },
                    )
                except pyjwt.InvalidTokenError:
                    continue
                if payload.get("sub") != sub:
                    continue
                try:
                    await self._redis.delete(cache_key)
                    deleted += 1
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "internal_token_cache.evict_delete_failed",
                        extra={
                            "key": cache_key,
                            "reason": type(exc).__name__,
                            "detail": str(exc),
                        },
                    )
        except Exception as exc:  # noqa: BLE001 — scan_iter is best-effort
            logger.warning(
                "internal_token_cache.evict_scan_failed",
                extra={"reason": type(exc).__name__, "detail": str(exc)},
            )
        if deleted:
            logger.info(
                "internal_token_cache.evicted_for_sub",
                extra={"sub": sub, "deleted": deleted},
            )
        return deleted

    # ── Internals ──────────────────────────────────────────────────────

    def _mint_fresh(
        self,
        keycloak_payload: JWTPayload | dict[str, Any],
        auth_method: AuthMethod,
    ) -> tuple[str, int]:
        return mint_internal_token(
            keycloak_payload=keycloak_payload,
            key_ring=self._key_ring,
            issuer=self._issuer,
            audience=self._audience,
            ttl_seconds=self._ttl_seconds,
            auth_method=auth_method,
        )
