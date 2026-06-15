#!/usr/bin/env python
"""Keycloak realm User-Profile schema sync (one-shot sidecar).

Keycloak's ``--import-realm`` only imports the realm on *first* boot against an
empty database. Edits to ``deploy/infra/keycloak-realm.json`` after that never reach a
running Keycloak whose pgdata already holds the old realm. The most
consequential casualty is the User-Profile schema: a realm imported before the
``tenant_id`` attribute existed has ``unmanagedAttributePolicy=DISABLED``, so
the gatekeeper ``/callback`` ``set_user_attribute('tenant_id', ...)`` silently
drops the value (the "Tenant assignment failed" 502).

This script reads the User-Profile JSON out of the mounted
``keycloak-realm.json`` and PUTs it to the running realm via the Admin API on
every ``docker compose up``, then reads it back to confirm. It runs once and
exits; the gatekeeper waits for ``service_completed_successfully`` before
booting. Dependency-light (stdlib + httpx) and reuses the gatekeeper image.

Env: ``KEYCLOAK_BASE_URL`` (…/realms), ``KEYCLOAK_ADMIN_REALM``,
``KC_ADMIN_USER``, ``KC_ADMIN_PASSWORD``, ``REALM_JSON_PATH``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

import httpx

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
logger = logging.getLogger("realm_sync")

_USER_PROFILE_PROVIDER_TYPE = "org.keycloak.userprofile.UserProfileProvider"
_MAX_ATTEMPTS = 8
_BACKOFF_BASE = 1.0
_BACKOFF_CEIL = 30.0


class RealmSyncError(RuntimeError):
    """Raised when the User-Profile schema cannot be synced or verified."""


def extract_user_profile_config(realm_json: dict[str, Any]) -> dict[str, Any]:
    """Parse the doubly-nested User-Profile JSON out of the realm JSON."""
    providers = (realm_json.get("components") or {}).get(_USER_PROFILE_PROVIDER_TYPE) or []
    if not providers:
        raise RealmSyncError(
            f"realm.json has no {_USER_PROFILE_PROVIDER_TYPE} component — refusing to sync"
        )
    raw = (providers[0].get("config") or {}).get("kc.user.profile.config")
    if not raw or not isinstance(raw, list) or not raw[0]:
        raise RealmSyncError("UserProfileProvider config['kc.user.profile.config'][0] missing")
    parsed = json.loads(raw[0])
    if not isinstance(parsed, dict):
        raise RealmSyncError("User-Profile JSON must be an object")
    return parsed


async def _admin_token(client: httpx.AsyncClient, base: str, user: str, pw: str) -> str:
    resp = await client.post(
        f"{base}/realms/master/protocol/openid-connect/token",
        data={"grant_type": "password", "username": user, "password": pw, "client_id": "admin-cli"},
    )
    if resp.status_code != 200:
        raise RealmSyncError(f"admin token grant failed: http={resp.status_code} {resp.text[:200]!r}")
    return resp.json()["access_token"]


async def sync(
    *,
    server_url: str,
    realm: str,
    admin_user: str,
    admin_password: str,
    profile_config: dict[str, Any],
    http_client: httpx.AsyncClient | None = None,
) -> None:
    """Acquire an admin token (retrying while Keycloak finishes booting), PUT
    the User-Profile config, and read it back to confirm tenant_id + policy."""
    base = server_url.rstrip("/")
    required = {a.get("name") for a in profile_config.get("attributes") or [] if isinstance(a, dict)}
    expected_policy = profile_config.get("unmanagedAttributePolicy")

    owns = http_client is None
    client = http_client or httpx.AsyncClient(timeout=30.0)

    async def _apply_once() -> dict[str, Any]:
        # Token + PUT + GET are retried together: Keycloak reports "healthy"
        # before the admin endpoints accept traffic, so the PUT/GET (not just
        # the token grant) can transiently fail right after boot.
        token = await _admin_token(client, base, admin_user, admin_password)
        put = await client.put(
            f"{base}/admin/realms/{realm}/users/profile",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json=profile_config,
        )
        if put.status_code not in (200, 204):
            raise RealmSyncError(f"PUT users/profile failed: http={put.status_code} {put.text[:200]!r}")
        got = await client.get(
            f"{base}/admin/realms/{realm}/users/profile",
            headers={"Authorization": f"Bearer {token}"},
        )
        if got.status_code != 200:
            raise RealmSyncError(f"GET users/profile failed: http={got.status_code}")
        return got.json()

    try:
        live = await _retry(_apply_once)
    finally:
        if owns:
            await client.aclose()

    live_attrs = {a.get("name") for a in live.get("attributes") or [] if isinstance(a, dict)}
    missing = required - live_attrs
    if missing:
        raise RealmSyncError(f"read-after-write: realm {realm!r} still missing attrs {sorted(missing)!r}")
    if expected_policy and live.get("unmanagedAttributePolicy") != expected_policy:
        raise RealmSyncError(
            f"read-after-write: unmanagedAttributePolicy is {live.get('unmanagedAttributePolicy')!r}, "
            f"expected {expected_policy!r}"
        )
    logger.info("realm sync ok: realm=%s attrs=%d policy=%s", realm, len(live_attrs), expected_policy)


async def _retry(fn: Any) -> Any:
    """Retry transient connect errors / 503s with bounded backoff; a 401/400
    (config error) is terminal."""
    delay = _BACKOFF_BASE
    last: BaseException | None = None
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            return await fn()
        except (httpx.ConnectError, httpx.ReadTimeout, httpx.RemoteProtocolError) as exc:
            last = exc
        except RealmSyncError as exc:
            if "http=503" not in str(exc):
                raise
            last = exc
        logger.warning("attempt %d/%d failed (%s); sleeping %.1fs", attempt, _MAX_ATTEMPTS, last, delay)
        await asyncio.sleep(delay)
        delay = min(delay * 2, _BACKOFF_CEIL)
    raise RealmSyncError(f"exhausted {_MAX_ATTEMPTS} attempts: {last}")


_DEV_ENVS = frozenset({"development", "dev", "test", "testing", "local", "ci"})


def _server_root(keycloak_base_url: str) -> str:
    """The admin API is rooted at the server, not under ``/realms``. Normalize
    ``http://kc:8080/realms`` AND ``http://kc:8080/realms/app`` (and a bare
    server URL) down to ``http://kc:8080`` by cutting at the first ``/realms``."""
    return keycloak_base_url.split("/realms", 1)[0].rstrip("/")


def main() -> int:
    base = _server_root(os.environ.get("KEYCLOAK_BASE_URL", "http://keycloak:8080/realms"))
    realm = os.environ.get("KEYCLOAK_ADMIN_REALM", "app")
    user = os.environ.get("KC_ADMIN_USER", "admin")
    pw = os.environ.get("KC_ADMIN_PASSWORD", "admin")
    realm_json_path = Path(os.environ.get("REALM_JSON_PATH", "/realm/keycloak-realm.json"))

    # Fail closed: never use the shipped dev admin password in a prod posture.
    env = os.environ.get("ENV", os.environ.get("ENVIRONMENT", "production")).strip().lower()
    if env not in _DEV_ENVS and pw == "admin":
        logger.error(
            "Refusing to run realm-sync in env=%s with the default KC_ADMIN_PASSWORD "
            "('admin'). Provide KC_ADMIN_PASSWORD from a secret.",
            env,
        )
        return 1
    try:
        realm_json = json.loads(realm_json_path.read_text(encoding="utf-8"))
        profile = extract_user_profile_config(realm_json)
        asyncio.run(
            sync(
                server_url=base,
                realm=realm,
                admin_user=user,
                admin_password=pw,
                profile_config=profile,
            )
        )
    except (RealmSyncError, OSError, json.JSONDecodeError) as exc:
        logger.error("realm sync FAILED: %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
