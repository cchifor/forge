"""S2SClient — outbound service-to-service auth.

Each :class:`S2SClient` instance targets a single downstream audience. It
obtains an audience-restricted bearer token via OAuth2 ``client_credentials``
(machine identity) or RFC 8693 token-exchange (on-behalf-of a user), caches
it until shortly before expiry, and attaches it to outbound HTTP calls.

Construction::

    workflow_to_knowledge = S2SClient(
        audience="svc-knowledge",
        token_endpoint="https://idp.example.com/realms/platform/protocol/openid-connect/token",
        client_id="svc-workflow",
        client_secret=settings.workflow_keycloak_secret,
    )

Usage in a request handler::

    response = await workflow_to_knowledge.get(
        "https://knowledge.svc/api/items",
        on_behalf_of=identity.raw_claims_token,  # the inbound user token
    )

Without ``on_behalf_of`` the call uses ``client_credentials`` and the
downstream sees a machine-identity token (no ``sub``). With it, the call
uses token-exchange and the downstream sees the user's identity preserved
plus ``act`` recording this service as the actor.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import httpx
import jwt as pyjwt
from jwt.exceptions import DecodeError, InvalidTokenError

from platform_auth.exceptions import S2SAuthError

_log = logging.getLogger(__name__)

# Token-exchange grant + token type identifiers per RFC 8693.
_GRANT_CLIENT_CREDENTIALS = "client_credentials"
_GRANT_TOKEN_EXCHANGE = "urn:ietf:params:oauth:grant-type:token-exchange"
_TOKEN_TYPE_ACCESS = "urn:ietf:params:oauth:token-type:access_token"

# Cache key for the client_credentials token (no subject).
_CLIENT_CREDENTIALS_KEY = "__client_credentials__"

DEFAULT_SAFETY_MARGIN_SECONDS = 60
"""Refresh cached tokens this many seconds before their natural expiry."""

DEFAULT_HTTP_TIMEOUT = 10.0
DEFAULT_MAX_CACHE_ENTRIES = 1024


@dataclass(slots=True)
class _CachedToken:
    token: str
    expires_at_monotonic: float


@dataclass(slots=True, frozen=True)
class CacheStats:
    """Snapshot of an :class:`S2SClient` instance's cache counters.

    Returned by :meth:`S2SClient.cache_stats`. Callers (each service's
    metrics module) decide whether/how to expose these as Prometheus
    counters — the SDK stays free of an HTTP-server / metrics
    framework dependency.
    """

    hits: int
    misses: int

    @property
    def hit_rate(self) -> float:
        total = self.hits + self.misses
        return 0.0 if total == 0 else self.hits / total


class S2SClient:
    """Audience-restricted outbound HTTP client."""

    def __init__(
        self,
        *,
        audience: str,
        token_endpoint: str,
        client_id: str,
        client_secret: str,
        http: httpx.AsyncClient | None = None,
        max_cache_entries: int = DEFAULT_MAX_CACHE_ENTRIES,
        safety_margin_seconds: int = DEFAULT_SAFETY_MARGIN_SECONDS,
        request_timeout: float = DEFAULT_HTTP_TIMEOUT,
    ) -> None:
        if not audience:
            raise ValueError("audience must be non-empty")
        if not token_endpoint:
            raise ValueError("token_endpoint must be non-empty")
        if not client_id:
            raise ValueError("client_id must be non-empty")
        if not client_secret:
            raise ValueError("client_secret must be non-empty")
        if max_cache_entries <= 0:
            raise ValueError("max_cache_entries must be positive")
        if safety_margin_seconds < 0:
            raise ValueError("safety_margin_seconds must be non-negative")

        self._audience = audience
        self._token_endpoint = token_endpoint
        self._client_id = client_id
        self._client_secret = client_secret
        self._owns_http = http is None
        self._http = http or httpx.AsyncClient(timeout=request_timeout)
        self._max_cache = max_cache_entries
        self._safety_margin = safety_margin_seconds
        self._tokens: dict[str, _CachedToken] = {}
        self._lock = asyncio.Lock()
        # Lifetime counters — cheap (no GIL contention beyond the already-
        # present asyncio.Lock) and surfaced via ``cache_stats()``.
        self._hits = 0
        self._misses = 0

    @property
    def audience(self) -> str:
        return self._audience

    # --------------------------------------------------------------- token API

    async def get_token(
        self,
        *,
        on_behalf_of: str | None = None,
        tenant_id: str | None = None,
    ) -> str:
        """Return a cached or freshly-obtained token for this client's audience.

        With ``on_behalf_of=<user_token>``, performs RFC 8693 token-exchange:
        the returned token preserves the user's ``sub`` and tenant, with
        ``act`` recording this service. Without it, performs a
        ``client_credentials`` grant for a machine-identity token.

        ``tenant_id`` is a platform extension to ``client_credentials``
        (RFC 6749 §4.4 doesn't define one). It scopes the minted token to
        a single tenant — required for multi-tenant calls where one
        ``client_id`` represents the same service across many tenants.
        It is ignored on token-exchange (tenant flows from
        ``subject_token``); passing both is harmless. Cache entries are
        keyed per-tenant so concurrent calls for different tenants don't
        share a token.

        Raises :class:`S2SAuthError` on token-endpoint failure.
        """
        cache_key = self._cache_key(on_behalf_of, tenant_id)
        cached = self._tokens.get(cache_key)
        now = time.monotonic()
        if cached is not None and now < cached.expires_at_monotonic:
            self._hits += 1
            return cached.token

        async with self._lock:
            cached = self._tokens.get(cache_key)
            now = time.monotonic()
            if cached is not None and now < cached.expires_at_monotonic:
                # Another coroutine raced ahead and refilled the cache
                # while we were waiting for the lock — count as a hit.
                self._hits += 1
                return cached.token

            self._misses += 1
            fresh = await self._fetch_token(on_behalf_of, tenant_id)
            self._tokens[cache_key] = fresh
            self._evict_if_full()
            return fresh.token

    def invalidate(
        self,
        *,
        on_behalf_of: str | None = None,
        tenant_id: str | None = None,
    ) -> None:
        """Drop the cached token for this subject; the next call refetches.

        Useful when the downstream returned 401 (token might be revoked
        upstream while still inside our cache window).
        """
        self._tokens.pop(self._cache_key(on_behalf_of, tenant_id), None)

    def clear_cache(self) -> None:
        """Drop every cached token. Use sparingly."""
        self._tokens.clear()

    def cache_stats(self) -> CacheStats:
        """Return a snapshot of the cache hit/miss counters.

        Counters are lifetime — they don't reset across calls. Each
        service's metrics module typically polls this on a Prometheus
        scrape and emits two gauges (``s2s_client_token_cache_hits``,
        ``s2s_client_token_cache_misses``) per ``audience``.
        """
        return CacheStats(hits=self._hits, misses=self._misses)

    # ---------------------------------------------------------------- HTTP API

    async def request(
        self,
        method: str,
        url: str,
        *,
        on_behalf_of: str | None = None,
        tenant_id: str | None = None,
        headers: Mapping[str, str] | None = None,
        **kwargs: Any,
    ) -> httpx.Response:
        """Send an authenticated request.

        On a 401 response we drop the cached token and retry once — the
        downstream may have rotated keys or revoked the token while it was
        still in our cache.
        """
        merged_headers = dict(headers) if headers else {}
        token = await self.get_token(on_behalf_of=on_behalf_of, tenant_id=tenant_id)
        merged_headers["Authorization"] = f"Bearer {token}"

        response = await self._http.request(method, url, headers=merged_headers, **kwargs)
        if response.status_code == 401:
            # Stale token — refetch and try once more.
            self.invalidate(on_behalf_of=on_behalf_of, tenant_id=tenant_id)
            token = await self.get_token(on_behalf_of=on_behalf_of, tenant_id=tenant_id)
            merged_headers["Authorization"] = f"Bearer {token}"
            response = await self._http.request(method, url, headers=merged_headers, **kwargs)
        return response

    async def get(self, url: str, **kwargs: Any) -> httpx.Response:
        return await self.request("GET", url, **kwargs)

    async def post(self, url: str, **kwargs: Any) -> httpx.Response:
        return await self.request("POST", url, **kwargs)

    async def put(self, url: str, **kwargs: Any) -> httpx.Response:
        return await self.request("PUT", url, **kwargs)

    async def patch(self, url: str, **kwargs: Any) -> httpx.Response:
        return await self.request("PATCH", url, **kwargs)

    async def delete(self, url: str, **kwargs: Any) -> httpx.Response:
        return await self.request("DELETE", url, **kwargs)

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    # -------------------------------------------------------------- internals

    def _cache_key(self, on_behalf_of: str | None, tenant_id: str | None) -> str:
        suffix = f":tenant:{tenant_id}" if tenant_id else ""
        if on_behalf_of is None:
            return _CLIENT_CREDENTIALS_KEY + suffix
        # Prefer the subject token's jti so two on-behalf-of calls for the
        # same user share a cache entry. Fall back to a hash so we never
        # store the raw token as a dict key.
        try:
            unverified = pyjwt.decode(
                on_behalf_of,
                options={
                    "verify_signature": False,
                    "verify_exp": False,
                    "verify_aud": False,
                    "verify_iss": False,
                    "verify_nbf": False,
                    "verify_iat": False,
                },
            )
            jti = unverified.get("jti")
            if isinstance(jti, str) and jti:
                return f"obo:jti:{jti}{suffix}"
        except (DecodeError, InvalidTokenError):
            pass
        digest = hashlib.sha256(on_behalf_of.encode("utf-8")).hexdigest()[:32]
        return f"obo:sha256:{digest}{suffix}"

    async def _fetch_token(
        self,
        on_behalf_of: str | None,
        tenant_id: str | None,
    ) -> _CachedToken:
        if on_behalf_of is None:
            data: dict[str, str] = {
                "grant_type": _GRANT_CLIENT_CREDENTIALS,
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "audience": self._audience,
            }
            if tenant_id is not None:
                data["tenant_id"] = tenant_id
        else:
            data = {
                "grant_type": _GRANT_TOKEN_EXCHANGE,
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "subject_token": on_behalf_of,
                "subject_token_type": _TOKEN_TYPE_ACCESS,
                "audience": self._audience,
            }
            # tenant_id ignored on token-exchange — the subject_token's
            # tenant is the source of truth. Don't send it; some servers
            # may reject extra params in strict mode.

        try:
            response = await self._http.post(self._token_endpoint, data=data)
        except httpx.HTTPError as exc:
            raise S2SAuthError(
                f"token endpoint unreachable: {exc!r}",
                token_endpoint=self._token_endpoint,
            ) from exc

        if response.status_code != 200:
            raise S2SAuthError(
                f"token endpoint returned HTTP {response.status_code}",
                status=response.status_code,
                body=_safe_text(response),
            )

        try:
            body = response.json()
        except ValueError as exc:
            raise S2SAuthError("token endpoint returned non-JSON response") from exc

        access_token = body.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            raise S2SAuthError(
                "token endpoint response missing 'access_token'",
                grant=data["grant_type"],
            )

        expires_in = body.get("expires_in")
        if not isinstance(expires_in, (int, float)) or expires_in <= 0:
            # Spec-compliant servers always return expires_in; default
            # defensively rather than refusing to cache.
            _log.warning(
                "token_endpoint_missing_expires_in",
                extra={"audience": self._audience},
            )
            expires_in = 300

        ttl = max(0.0, float(expires_in) - self._safety_margin)
        return _CachedToken(
            token=access_token,
            expires_at_monotonic=time.monotonic() + ttl,
        )

    def _evict_if_full(self) -> None:
        if len(self._tokens) <= self._max_cache:
            return
        # Evict the entry closest to expiry (least useful going forward).
        # Iterating dict.items() is O(n); n is bounded by max_cache so this
        # stays cheap.
        oldest_key = min(self._tokens, key=lambda k: self._tokens[k].expires_at_monotonic)
        self._tokens.pop(oldest_key, None)


def _safe_text(response: httpx.Response) -> str:
    """Return a short, log-safe excerpt of a response body.

    Keeps the audit trail useful when token endpoints fail without leaking
    a megabyte of HTML into structured logs.
    """
    try:
        text = response.text
    except (UnicodeDecodeError, ValueError):
        return "<unreadable>"
    return text[:200]


__all__ = [
    "DEFAULT_HTTP_TIMEOUT",
    "DEFAULT_MAX_CACHE_ENTRIES",
    "DEFAULT_SAFETY_MARGIN_SECONDS",
    "CacheStats",
    "S2SClient",
]
