"""Service-to-service (S2S) token client for the API gateway.

Mints OAuth2 client-credentials tokens against the gatekeeper token endpoint
and caches them in-memory **per audience** until shortly before expiry,
re-minting on demand. Keying the cache by audience is essential: a token
addressed to one downstream (e.g. ``orders``) must never be replayed against
another (``inventory``) — that would be an audience-confusion bug. The minted
token is attached as a bearer ``Authorization`` header on requests the gateway
proxies to downstream services.

Configuration is read from the environment:

    GATEKEEPER_CLIENT_ID       -- the gateway's client id
    GATEKEEPER_CLIENT_SECRET   -- the gateway's client secret
    GATEKEEPER_TOKEN_ENDPOINT  -- the client-credentials token URL

When any of these is absent the client degrades gracefully:
:meth:`S2SClient.auth_header` returns an empty dict, so the gateway still
proxies (un-authenticated) in environments where S2S is not configured. This
keeps the generated gateway runnable in any configuration.

Self-contained — depends only on ``httpx`` (already a base dependency) and the
standard library; it does NOT import the ``platform_auth`` SDK.
"""

from __future__ import annotations

import asyncio
import os
import time

import httpx

#: Re-mint this many seconds before the token's stated expiry to absorb clock
#: skew and request latency rather than racing the exact expiry instant.
_EXPIRY_SKEW_SECONDS = 30.0

#: Fallback lifetime (seconds) when the token response omits ``expires_in``.
_DEFAULT_EXPIRES_IN = 300.0

#: Bound the token-mint call so a slow gatekeeper can't hang a proxied request.
_MINT_TIMEOUT = httpx.Timeout(10.0, connect=5.0)


class S2SMintError(RuntimeError):
    """Raised when minting an S2S token fails (transport, status, or shape).

    Callers (the proxy) catch this to return a gateway 502/503 instead of an
    opaque 500: a gatekeeper outage or a malformed token response is an
    upstream-dependency failure, not a bug in the gateway itself.
    """


class S2SClient:
    """Async client-credentials token client with in-memory caching.

    Thread/task-safe for concurrent callers within one event loop: a lock
    serialises minting so a token burst results in a single round-trip.
    """

    def __init__(
        self,
        *,
        client_id: str | None = None,
        client_secret: str | None = None,
        token_endpoint: str | None = None,
    ) -> None:
        # Explicit args win; otherwise fall back to the environment so the
        # default construction path (S2SClient()) is fully env-driven.
        self._client_id = client_id or os.environ.get("GATEKEEPER_CLIENT_ID", "")
        self._client_secret = client_secret or os.environ.get("GATEKEEPER_CLIENT_SECRET", "")
        self._token_endpoint = token_endpoint or os.environ.get("GATEKEEPER_TOKEN_ENDPOINT", "")
        # Cache keyed by audience: a token minted for ``orders`` must NOT be
        # reused for ``inventory`` (audience confusion). Each entry is a
        # ``(token, monotonic_expiry)`` tuple. The default-audience (``None``)
        # token lives under its own key like any other.
        self._cache: dict[str | None, tuple[str, float]] = {}
        # A single lock guards minting; under it we re-check the per-audience
        # cache entry so a burst for one audience results in one round-trip
        # while still minting distinct tokens for distinct audiences.
        self._lock = asyncio.Lock()

    @property
    def configured(self) -> bool:
        """True when client id, secret, and token endpoint are all present."""
        return bool(self._client_id and self._client_secret and self._token_endpoint)

    def _fresh_token(self, audience: str | None) -> str | None:
        """Return the cached token for ``audience`` if still fresh, else None."""
        entry = self._cache.get(audience)
        if entry is None:
            return None
        token, expires_at = entry
        if time.monotonic() < expires_at:
            return token
        return None

    async def _mint(self, audience: str | None) -> str:
        """POST the client-credentials grant and cache the resulting token.

        Raises :class:`S2SMintError` on any failure (transport error, non-2xx
        status, or a malformed token response missing ``access_token``) so the
        caller can map it to a gateway 502 rather than leaking a 500.
        """
        form: dict[str, str] = {
            "grant_type": "client_credentials",
            "client_id": self._client_id,
            "client_secret": self._client_secret,
        }
        if audience:
            form["audience"] = audience
        try:
            async with httpx.AsyncClient(timeout=_MINT_TIMEOUT) as client:
                resp = await client.post(self._token_endpoint, data=form)
                resp.raise_for_status()
                payload = resp.json()
        except httpx.HTTPError as exc:
            raise S2SMintError(f"token mint request failed: {exc}") from exc
        if not isinstance(payload, dict) or "access_token" not in payload:
            # A malformed/error body (e.g. ``{"error": "invalid_client"}``)
            # must surface as a clean mint failure, not a KeyError 500.
            raise S2SMintError("token response missing 'access_token'")
        token = str(payload["access_token"])
        expires_in = float(payload.get("expires_in", _DEFAULT_EXPIRES_IN))
        expires_at = time.monotonic() + max(expires_in - _EXPIRY_SKEW_SECONDS, 0.0)
        self._cache[audience] = (token, expires_at)
        return token

    async def token(self, audience: str | None = None) -> str | None:
        """Return a valid token, minting/refreshing as needed (or ``None``).

        Returns ``None`` when S2S is not configured. A cached token is reused
        per-audience until it nears expiry; concurrent callers for the same
        audience share a single mint. Raises :class:`S2SMintError` if minting
        fails for a configured client.
        """
        if not self.configured:
            return None
        cached = self._fresh_token(audience)
        if cached is not None:
            return cached
        async with self._lock:
            # Re-check the per-audience entry under the lock: another task may
            # have just minted for THIS audience while we waited.
            cached = self._fresh_token(audience)
            if cached is not None:
                return cached
            return await self._mint(audience)

    async def auth_header(self, audience: str | None = None) -> dict[str, str]:
        """Return ``{"Authorization": "Bearer <token>"}`` or an empty dict.

        Empty when S2S credentials are absent, so the caller proxies without an
        Authorization header rather than failing.
        """
        token = await self.token(audience)
        if not token:
            return {}
        return {"Authorization": f"Bearer {token}"}
