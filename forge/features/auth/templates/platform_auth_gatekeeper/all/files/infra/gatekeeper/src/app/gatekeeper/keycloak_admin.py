# src/app/gatekeeper/keycloak_admin.py
"""
Tiny Keycloak Admin REST client for the gatekeeper.

Used by ``/callback`` to assign a default ``tenant_id`` attribute to
self-registered users whose access tokens lack the
``https://forge/tenant_id`` claim. Authenticates via the
``client_credentials`` grant on the same confidential client the
gatekeeper already uses for the OIDC flow (now with
``serviceAccountsEnabled=true`` and a ``manage-users`` role).

Design:
- Single class, three public methods.
- Reuses the gatekeeper's shared :class:`httpx.AsyncClient` so requests
  go through the same connection pool, retry decorator (where applied),
  and ``MockTransport`` in tests.
- Caches the admin token by monotonic wall-clock minus a 30s safety
  margin to avoid using a token that's about to expire mid-request.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from app.gatekeeper.http_client import get_http_client

logger = logging.getLogger(__name__)


class GatekeeperKeycloakAdmin:
    """Async client for the Keycloak Admin REST API, scoped to the
    ``manage-users`` role on a single realm.
    """

    def __init__(
        self,
        *,
        server_url: str,
        realm: str,
        client_id: str,
        client_secret: str,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._server_url = server_url.rstrip("/")
        self._realm = realm
        self._client_id = client_id
        self._client_secret = client_secret
        self._http_client = http_client
        self._token: str | None = None
        self._token_expires_at: float = 0.0

    def _client(self) -> httpx.AsyncClient:
        return self._http_client or get_http_client()

    def _token_url(self) -> str:
        return f"{self._server_url}/realms/{self._realm}/protocol/openid-connect/token"

    def _user_url(self, user_id: str) -> str:
        return f"{self._server_url}/admin/realms/{self._realm}/users/{user_id}"

    async def _get_admin_token(self) -> str:
        if self._token and time.monotonic() < self._token_expires_at:
            return self._token

        resp = await self._client().post(
            self._token_url(),
            data={
                "grant_type": "client_credentials",
                "client_id": self._client_id,
                "client_secret": self._client_secret,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        self._token = data["access_token"]
        # 30-second safety margin: refuse to reuse a token within 30s of
        # its declared expiry. With expires_in <= 30 the cached entry is
        # already-expired, so every call fetches fresh.
        self._token_expires_at = time.monotonic() + int(data.get("expires_in", 60)) - 30
        return self._token

    async def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {await self._get_admin_token()}",
            "Content-Type": "application/json",
        }

    async def get_user(self, user_id: str) -> dict[str, Any]:
        resp = await self._client().get(
            self._user_url(user_id),
            headers=await self._headers(),
        )
        resp.raise_for_status()
        return resp.json()

    async def set_user_attribute(self, user_id: str, attr: str, value: str) -> None:
        """Read the user, set ``attributes[attr] = [value]`` while
        preserving any other attribute keys, then PUT the user back."""
        user = await self.get_user(user_id)
        attributes = dict(user.get("attributes") or {})
        attributes[attr] = [value]
        user["attributes"] = attributes

        resp = await self._client().put(
            self._user_url(user_id),
            headers=await self._headers(),
            json=user,
        )
        resp.raise_for_status()
