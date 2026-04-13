"""OAuth2 Client Credentials token manager with caching."""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class ClientCredentialsAuth:
    """Manages an OAuth2 client-credentials access token with auto-refresh.

    Tokens are cached in memory and refreshed when they are within
    ``refresh_margin`` seconds of expiry.
    """

    def __init__(
        self,
        token_url: str,
        client_id: str,
        client_secret: str,
        *,
        scopes: list[str] | None = None,
        refresh_margin: float = 30.0,
    ):
        self._token_url = token_url
        self._client_id = client_id
        self._client_secret = client_secret
        self._scopes = scopes or []
        self._refresh_margin = refresh_margin

        self._access_token: str | None = None
        self._expires_at: float = 0.0

    @property
    def is_expired(self) -> bool:
        return time.monotonic() >= (self._expires_at - self._refresh_margin)

    async def get_token(self, client: httpx.AsyncClient) -> str:
        if self._access_token and not self.is_expired:
            return self._access_token

        data: dict[str, Any] = {
            "grant_type": "client_credentials",
            "client_id": self._client_id,
            "client_secret": self._client_secret,
        }
        if self._scopes:
            data["scope"] = " ".join(self._scopes)

        response = await client.post(self._token_url, data=data)
        response.raise_for_status()
        payload = response.json()

        self._access_token = payload["access_token"]
        expires_in = payload.get("expires_in", 300)
        self._expires_at = time.monotonic() + expires_in

        logger.debug("Token refreshed, expires in %ds", expires_in)
        return self._access_token  # type: ignore[return-value]

    @classmethod
    def from_keycloak(
        cls,
        server_url: str,
        realm: str,
        client_id: str,
        client_secret: str,
    ) -> "ClientCredentialsAuth":
        token_url = f"{server_url.rstrip('/')}/realms/{realm}/protocol/openid-connect/token"
        return cls(
            token_url=token_url,
            client_id=client_id,
            client_secret=client_secret,
        )
