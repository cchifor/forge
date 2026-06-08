"""Boot-time realm invariant probes.

A recurring auth-chain failure is that the running Keycloak's User-Profile
schema can silently drift from ``infra/keycloak-realm.json``. When it does,
gatekeeper's ``/callback`` ``set_user_attribute('tenant_id', ...)`` raises only
on the *first* self-registration — every prior boot looked fine.

The ``keycloak-realm-sync`` compose sidecar reconciles the schema before
gatekeeper boots, but that ``depends_on`` guarantee does not apply in
Helm/k8s, where the gatekeeper pod and the sync Job race independently.
This module's job is to verify the invariant on every gatekeeper boot
and refuse to come up otherwise — converting a future user-facing 502
into a loud boot-time crash that surfaces on the deploy dashboard.

The check is **read-only** (GET /admin/realms/{realm}/users/profile),
so the gatekeeper service can hold admin credentials without the
privilege-creep concern that would attend a *write* path. The full
schema *sync* is intentionally elsewhere.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class RealmInvariantError(RuntimeError):
    """Raised when a required realm invariant doesn't hold.

    Carries the same diagnostic shape as
    :class:`app.gatekeeper.keycloak_admin.GatekeeperKeycloakAdmin.set_user_attribute`'s
    silent-drop message so operators see one consistent error string
    whether the drift surfaces at boot or at first registration.
    """


async def verify_user_profile_active(
    *,
    server_url: str,
    realm: str,
    admin_user: str,
    admin_password: str,
    required_attributes: frozenset[str] = frozenset(["tenant_id"]),
    required_policy: str = "ADMIN_EDIT",
    http_client: httpx.AsyncClient | None = None,
    timeout: float = 10.0,
) -> None:
    """Read the live User-Profile schema; raise if the invariant fails.

    Invariant:
    - Every name in ``required_attributes`` appears in the live
      ``attributes`` list. Without this the gatekeeper's read-after-write
      on ``set_user_attribute`` silently drops the value.
    - ``unmanagedAttributePolicy`` equals ``required_policy``. Without
      this Keycloak defaults to ``DISABLED``, which drops any attribute
      that isn't explicitly declared — including the ``tenant_id`` that
      legacy users might still need.

    Raises :class:`RealmInvariantError` on any divergence with the same
    diagnostic the silent-drop guard already produces. Network errors
    (Keycloak unreachable) also raise — the gatekeeper is useless without
    its IdP, so failing fast is the right behavior at boot.
    """
    base = server_url.rstrip("/")
    token_url = f"{base}/realms/master/protocol/openid-connect/token"
    profile_url = f"{base}/admin/realms/{realm}/users/profile"

    owns_client = http_client is None
    client = http_client or httpx.AsyncClient(timeout=timeout)
    try:
        token_resp = await client.post(
            token_url,
            data={
                "grant_type": "password",
                "username": admin_user,
                "password": admin_password,
                "client_id": "admin-cli",
            },
        )
        if token_resp.status_code != 200:
            raise RealmInvariantError(
                f"realm invariant probe: master admin token grant failed at "
                f"{token_url}: http={token_resp.status_code} body={token_resp.text[:200]!r}. "
                "Check KC_ADMIN_USER / KC_ADMIN_PASSWORD env on the gatekeeper "
                "service (in prod these MUST come from a k8s Secret, not literal env)."
            )
        token = token_resp.json()["access_token"]

        profile_resp = await client.get(
            profile_url,
            headers={"Authorization": f"Bearer {token}"},
        )
        if profile_resp.status_code != 200:
            raise RealmInvariantError(
                f"realm invariant probe: GET {profile_url} failed: "
                f"http={profile_resp.status_code} body={profile_resp.text[:200]!r}."
            )
        profile = profile_resp.json()
    finally:
        if owns_client:
            await client.aclose()

    live_attrs = _live_attribute_names(profile)
    missing = required_attributes - live_attrs
    if missing:
        raise RealmInvariantError(
            f"realm invariant probe: User-Profile schema on realm {realm!r} "
            f"is missing required attribute(s) {sorted(missing)!r}. The "
            "gatekeeper's set_user_attribute would silently drop these on "
            "self-registration. Most likely the keycloak-realm-sync sidecar "
            "did not run, or pgdata holds a stale schema. Add the attribute "
            "under components['org.keycloak.userprofile.UserProfileProvider'][0]"
            ".config['kc.user.profile.config'] in infra/keycloak-realm.json, "
            "or apply directly to a running realm via "
            "PUT /admin/realms/{realm}/users/profile (which is exactly what "
            "the keycloak-realm-sync sidecar does)."
        )

    live_policy = profile.get("unmanagedAttributePolicy")
    if live_policy != required_policy:
        raise RealmInvariantError(
            f"realm invariant probe: unmanagedAttributePolicy on realm "
            f"{realm!r} is {live_policy!r}; expected {required_policy!r}. "
            "With DISABLED, KC silently drops any attribute not declared in "
            "the schema — the original 502 'Tenant assignment failed' "
            "failure mode. Run keycloak-realm-sync (or apply realm.json "
            "via PUT /admin/realms/{realm}/users/profile) to reconcile."
        )
    logger.info(
        "realm invariant ok: realm=%s attrs=%d policy=%s",
        realm,
        len(profile.get("attributes") or []),
        live_policy,
    )


def _live_attribute_names(profile: dict[str, Any]) -> set[str]:
    return {
        attr.get("name", "")
        for attr in profile.get("attributes") or []
        if isinstance(attr, dict) and attr.get("name")
    }
