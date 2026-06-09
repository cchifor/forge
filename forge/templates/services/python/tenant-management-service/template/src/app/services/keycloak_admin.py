# src/app/services/keycloak_admin.py
"""
Keycloak Admin REST API client for realm, client, and user provisioning.
"""

from __future__ import annotations

import logging
import time

import httpx

from forge_core.errors import ApplicationError

logger = logging.getLogger(__name__)


class KeycloakAdminClient:
    """Async client for the Keycloak Admin REST API."""

    def __init__(
        self,
        base_url: str,
        admin_user: str,
        admin_password: str,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._admin_user = admin_user
        self._admin_password = admin_password
        self._client = httpx.AsyncClient(timeout=30.0)
        self._token: str | None = None
        self._token_expires_at: float = 0.0

    async def close(self) -> None:
        await self._client.aclose()

    # ── Admin token management ────────────────────────────────────────────

    async def _get_admin_token(self) -> str:
        """Obtain or reuse a cached admin access token."""
        if self._token and time.monotonic() < self._token_expires_at - 30:
            return self._token

        logger.debug("Refreshing Keycloak admin token")
        resp = await self._client.post(
            f"{self._base_url}/realms/master/protocol/openid-connect/token",
            data={
                "grant_type": "password",
                "client_id": "admin-cli",
                "username": self._admin_user,
                "password": self._admin_password,
            },
        )
        if resp.status_code == 401:
            raise ApplicationError("Keycloak admin authentication failed — check credentials")
        resp.raise_for_status()

        data = resp.json()
        self._token = data["access_token"]
        self._token_expires_at = time.monotonic() + data.get("expires_in", 60)
        return self._token

    async def _headers(self) -> dict[str, str]:
        token = await self._get_admin_token()
        return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    @staticmethod
    def _extract_id_from_location(resp: httpx.Response, entity: str) -> str:
        """Extract the resource ID from a Keycloak Location header."""
        location = resp.headers.get("location")
        if not location:
            raise ApplicationError(f"Keycloak did not return Location header for {entity}")
        return location.rstrip("/").split("/")[-1]

    # ── Realm operations ──────────────────────────────────────────────────

    async def create_realm(self, realm_name: str, display_name: str | None = None) -> None:
        """Create a new Keycloak realm. Idempotent — ignores 409 Conflict."""
        headers = await self._headers()
        payload = {
            "realm": realm_name,
            "enabled": True,
            "displayName": display_name or realm_name,
            "sslRequired": "none",
            "registrationAllowed": False,
            "loginWithEmailAllowed": True,
        }
        resp = await self._client.post(
            f"{self._base_url}/admin/realms",
            json=payload,
            headers=headers,
        )
        if resp.status_code == 409:
            logger.warning("Realm '%s' already exists in Keycloak (idempotent)", realm_name)
            return
        resp.raise_for_status()
        logger.info("Created Keycloak realm: %s", realm_name)

    async def delete_realm(self, realm_name: str) -> None:
        """Delete a Keycloak realm."""
        headers = await self._headers()
        resp = await self._client.delete(
            f"{self._base_url}/admin/realms/{realm_name}",
            headers=headers,
        )
        if resp.status_code == 404:
            logger.warning("Realm '%s' not found in Keycloak (already deleted?)", realm_name)
            return
        resp.raise_for_status()
        logger.info("Deleted Keycloak realm: %s", realm_name)

    # ── Client operations ─────────────────────────────────────────────────

    async def create_client(
        self,
        realm_name: str,
        client_id: str,
        redirect_uris: list[str] | None = None,
    ) -> str:
        """Register an OIDC client in a realm. Returns the client_secret."""
        headers = await self._headers()
        payload = {
            "clientId": client_id,
            "enabled": True,
            "clientAuthenticatorType": "client-secret",
            "publicClient": False,
            "directAccessGrantsEnabled": True,
            "standardFlowEnabled": True,
            "redirectUris": redirect_uris or ["*"],
            "webOrigins": ["*"],
            "protocol": "openid-connect",
        }
        resp = await self._client.post(
            f"{self._base_url}/admin/realms/{realm_name}/clients",
            json=payload,
            headers=headers,
        )
        if resp.status_code == 409:
            # Client already exists — look it up and return its secret
            logger.warning(
                "Client '%s' already exists in realm '%s' (idempotent)", client_id, realm_name
            )
            lookup = await self._client.get(
                f"{self._base_url}/admin/realms/{realm_name}/clients",
                params={"clientId": client_id},
                headers=headers,
            )
            lookup.raise_for_status()
            clients = lookup.json()
            if clients:
                internal_id = clients[0]["id"]
                secret_resp = await self._client.get(
                    f"{self._base_url}/admin/realms/{realm_name}/clients/{internal_id}/client-secret",
                    headers=headers,
                )
                secret_resp.raise_for_status()
                return secret_resp.json().get("value", "")
            raise ApplicationError(
                f"Client '{client_id}' conflict but not found in realm '{realm_name}'"
            )
        resp.raise_for_status()

        internal_id = self._extract_id_from_location(resp, f"client '{client_id}'")

        # Fetch the client secret
        secret_resp = await self._client.get(
            f"{self._base_url}/admin/realms/{realm_name}/clients/{internal_id}/client-secret",
            headers=headers,
        )
        secret_resp.raise_for_status()
        client_secret = secret_resp.json().get("value", "")
        if not client_secret:
            raise ApplicationError(
                f"Keycloak returned empty client_secret for '{client_id}' in realm '{realm_name}'"
            )
        logger.info("Created OIDC client '%s' in realm '%s'", client_id, realm_name)
        return client_secret

    # ── User operations ───────────────────────────────────────────────────

    async def create_user(
        self,
        realm_name: str,
        username: str,
        email: str,
        password: str,
        realm_roles: list[str] | None = None,
    ) -> str:
        """Create a user in a realm. Returns the user UUID."""
        headers = await self._headers()
        payload = {
            "username": username,
            "email": email,
            "emailVerified": True,
            "enabled": True,
            "credentials": [{"type": "password", "value": password, "temporary": False}],
        }
        resp = await self._client.post(
            f"{self._base_url}/admin/realms/{realm_name}/users",
            json=payload,
            headers=headers,
        )
        resp.raise_for_status()

        user_id = self._extract_id_from_location(resp, f"user '{username}'")

        if realm_roles:
            await self._assign_realm_roles(realm_name, user_id, realm_roles, headers)

        logger.info("Created user '%s' in realm '%s' (id=%s)", username, realm_name, user_id)
        return user_id

    async def _assign_realm_roles(
        self,
        realm_name: str,
        user_id: str,
        role_names: list[str],
        headers: dict[str, str],
    ) -> None:
        """Assign realm-level roles to a user."""
        resp = await self._client.get(
            f"{self._base_url}/admin/realms/{realm_name}/roles",
            headers=headers,
        )
        resp.raise_for_status()
        all_roles = {r["name"]: r for r in resp.json()}

        roles_to_assign = [all_roles[n] for n in role_names if n in all_roles]
        missing = [n for n in role_names if n not in all_roles]
        if missing:
            logger.warning("Roles not found in realm '%s': %s — skipping", realm_name, missing)

        if roles_to_assign:
            await self._client.post(
                f"{self._base_url}/admin/realms/{realm_name}/users/{user_id}/role-mappings/realm",
                json=roles_to_assign,
                headers=headers,
            )
