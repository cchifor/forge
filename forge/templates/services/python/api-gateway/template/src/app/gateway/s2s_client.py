"""Service-to-service (S2S) token client for the API gateway.

Mints OAuth2 client-credentials tokens against the gatekeeper token endpoint
and caches them in-memory until shortly before expiry, re-minting on demand.
The minted token is attached as a bearer ``Authorization`` header on requests
the gateway proxies to downstream services.

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
        self._token: str | None = None
        self._expires_at: float = 0.0
        self._lock = asyncio.Lock()

    @property
    def configured(self) -> bool:
        """True when client id, secret, and token endpoint are all present."""
        return bool(self._client_id and self._client_secret and self._token_endpoint)

    def _is_fresh(self) -> bool:
        return self._token is not None and time.monotonic() < self._expires_at

    async def _mint(self, audience: str | None) -> str:
        """POST the client-credentials grant and cache the resulting token."""
        form: dict[str, str] = {
            "grant_type": "client_credentials",
            "client_id": self._client_id,
            "client_secret": self._client_secret,
        }
        if audience:
            form["audience"] = audience
        async with httpx.AsyncClient(timeout=_MINT_TIMEOUT) as client:
            resp = await client.post(self._token_endpoint, data=form)
            resp.raise_for_status()
            payload = resp.json()
        token = str(payload["access_token"])
        expires_in = float(payload.get("expires_in", _DEFAULT_EXPIRES_IN))
        self._token = token
        self._expires_at = time.monotonic() + max(expires_in - _EXPIRY_SKEW_SECONDS, 0.0)
        return token

    async def token(self, audience: str | None = None) -> str | None:
        """Return a valid token, minting/refreshing as needed (or ``None``).

        Returns ``None`` when S2S is not configured. A cached token is reused
        until it nears expiry; concurrent callers share a single mint.
        """
        if not self.configured:
            return None
        if self._is_fresh():
            return self._token
        async with self._lock:
            # Re-check under the lock: another task may have just minted.
            if self._is_fresh():
                return self._token
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
