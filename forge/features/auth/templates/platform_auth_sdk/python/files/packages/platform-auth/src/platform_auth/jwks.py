"""Asynchronous, multi-issuer JWKS cache with key rotation and graceful staleness.

The cache holds the JWKS document for each registered issuer in memory. A
fetch is triggered on first use, when the cache is older than ``lifespan``,
or when a token presents a ``kid`` we have never seen (most likely a key
rotation). On upstream failure the cache serves the last known good
document for up to ``stale_max`` seconds so a transient Keycloak outage
does not flatline every service.

The cache is safe under concurrent ``get_signing_key`` calls: a single
``asyncio.Lock`` serializes refreshes so we never thundering-herd the IdP.

Constructed once per process (typically inside ``AuthGuard``); never per
request.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any

import httpx
import jwt as pyjwt

from platform_auth.exceptions import InvalidToken

_log = logging.getLogger(__name__)

# Default cache lifetimes; configurable per instance.
DEFAULT_LIFESPAN_SECONDS = 600  # 10 min between voluntary refreshes
DEFAULT_STALE_MAX_SECONDS = 1800  # 30 min after which stale-serve is refused
DEFAULT_HTTP_TIMEOUT = 5.0


@dataclass(slots=True)
class _CacheEntry:
    fetched_at_monotonic: float
    keys_by_kid: dict[str, pyjwt.PyJWK]


class JWKSCache:
    """Multi-issuer JWKS cache.

    Lifecycle:

    1. Caller registers every trusted issuer at startup via
       :meth:`register_issuer`. Issuers absent from the registry will raise
       :class:`KeyError` on lookup — verifiers are expected to consult the
       tenant→issuer trust map *before* asking JWKS, so an unregistered
       lookup is a programmer error rather than a runtime auth decision.
    2. :meth:`get_signing_key` returns the JWK for ``(issuer, kid)``. On a
       miss or unknown ``kid``, the cache fetches the JWKS document and
       retries; on upstream failure within the staleness window, it serves
       the last known good document.
    3. :meth:`aclose` releases the underlying httpx client when the cache
       owns it.
    """

    def __init__(
        self,
        *,
        lifespan_seconds: int = DEFAULT_LIFESPAN_SECONDS,
        stale_max_seconds: int = DEFAULT_STALE_MAX_SECONDS,
        http_timeout: float = DEFAULT_HTTP_TIMEOUT,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        if lifespan_seconds <= 0:
            raise ValueError("lifespan_seconds must be positive")
        if stale_max_seconds < lifespan_seconds:
            raise ValueError(
                "stale_max_seconds must be >= lifespan_seconds; otherwise stale-serve "
                "would be a no-op"
            )

        self._lifespan = lifespan_seconds
        self._stale_max = stale_max_seconds
        self._http_timeout = http_timeout
        self._owns_http = http_client is None
        self._http = http_client or httpx.AsyncClient(timeout=http_timeout)
        self._jwks_uris: dict[str, str] = {}
        self._cache: dict[str, _CacheEntry] = {}
        self._lock = asyncio.Lock()

    def register_issuer(self, issuer: str, jwks_uri: str) -> None:
        """Register an issuer's JWKS URI.

        Idempotent — calling with the same arguments twice is a no-op. Calling
        with a different URI for an existing issuer replaces it and clears
        any cached entry, so config reloads pick up cleanly.
        """
        if not issuer:
            raise ValueError("issuer must be non-empty")
        if not jwks_uri:
            raise ValueError("jwks_uri must be non-empty")
        existing = self._jwks_uris.get(issuer)
        if existing == jwks_uri:
            return
        self._jwks_uris[issuer] = jwks_uri
        self._cache.pop(issuer, None)

    def registered_issuers(self) -> frozenset[str]:
        """Return the set of issuers that may be looked up.

        Useful for the trust-map verifier as a pre-check, and for diagnostic
        endpoints.
        """
        return frozenset(self._jwks_uris)

    async def get_signing_key(self, issuer: str, kid: str) -> pyjwt.PyJWK:
        """Return the JWK that signs tokens with ``kid`` from ``issuer``.

        Raises :class:`KeyError` if ``issuer`` is not registered; raises
        :class:`InvalidToken` if the JWKS does not contain ``kid`` after a
        forced refresh, or if the upstream is unreachable and the staleness
        window has elapsed.
        """
        if issuer not in self._jwks_uris:
            raise KeyError(f"issuer not registered: {issuer!r}")

        # Fast path: fresh cache + kid present.
        entry = self._cache.get(issuer)
        now = time.monotonic()
        if (
            entry is not None
            and (now - entry.fetched_at_monotonic) < self._lifespan
            and kid in entry.keys_by_kid
        ):
            return entry.keys_by_kid[kid]

        # Slow path: refresh under lock. Double-checked locking pattern so
        # the second arrival to a kid-rotation event reuses the first
        # arrival's fetched JWKS instead of fetching again.
        async with self._lock:
            entry = self._cache.get(issuer)
            now = time.monotonic()
            if (
                entry is not None
                and (now - entry.fetched_at_monotonic) < self._lifespan
                and kid in entry.keys_by_kid
            ):
                return entry.keys_by_kid[kid]

            try:
                fresh = await self._fetch(self._jwks_uris[issuer])
            except Exception as exc:
                if (
                    entry is not None
                    and (now - entry.fetched_at_monotonic) < self._stale_max
                    and kid in entry.keys_by_kid
                ):
                    _log.warning(
                        "jwks_fetch_failed_serving_stale",
                        extra={
                            "issuer": issuer,
                            "kid": kid,
                            "age_seconds": now - entry.fetched_at_monotonic,
                            "error": str(exc),
                        },
                    )
                    return entry.keys_by_kid[kid]
                raise InvalidToken(
                    f"JWKS unavailable for issuer {issuer!r} and stale window expired"
                ) from exc

            self._cache[issuer] = _CacheEntry(
                fetched_at_monotonic=time.monotonic(),
                keys_by_kid=fresh,
            )
            if kid not in fresh:
                raise InvalidToken(
                    f"unknown signing key kid {kid!r} for issuer {issuer!r} (JWKS refreshed)"
                )
            return fresh[kid]

    async def _fetch(self, jwks_uri: str) -> dict[str, pyjwt.PyJWK]:
        resp = await self._http.get(jwks_uri, timeout=self._http_timeout)
        resp.raise_for_status()
        data: Any = resp.json()
        if not isinstance(data, dict):
            raise ValueError("JWKS response is not a JSON object")
        keys = data.get("keys")
        if not isinstance(keys, list):
            raise ValueError("JWKS response missing 'keys' array")
        result: dict[str, pyjwt.PyJWK] = {}
        for raw in keys:
            if not isinstance(raw, dict):
                continue
            kid = raw.get("kid")
            if not isinstance(kid, str):
                # Keys without a 'kid' cannot be selected by JWT header; skip.
                continue
            # Skip keys explicitly marked for non-signing use (Keycloak ships
            # an ``RSA-OAEP / use=enc`` encryption key alongside the RS256
            # signing key by default). The ``PyJWK`` constructor raises
            # ``PyJWKError`` for keys whose alg lookup fails, and a single
            # bad entry must not fail the whole fetch — without this filter
            # the entire JWKS load aborts on the first non-signing key.
            use = raw.get("use")
            if isinstance(use, str) and use != "sig":
                continue
            try:
                result[kid] = pyjwt.PyJWK(raw)
            except (pyjwt.InvalidKeyError, pyjwt.PyJWKError, ValueError) as exc:
                _log.warning(
                    "jwks_key_skipped",
                    extra={"kid": kid, "error": str(exc)},
                )
        if not result:
            raise ValueError("JWKS document yielded no usable signing keys")
        return result

    async def aclose(self) -> None:
        """Release the underlying HTTP client if this cache owns it."""
        if self._owns_http:
            await self._http.aclose()


__all__ = ["DEFAULT_LIFESPAN_SECONDS", "DEFAULT_STALE_MAX_SECONDS", "JWKSCache"]
