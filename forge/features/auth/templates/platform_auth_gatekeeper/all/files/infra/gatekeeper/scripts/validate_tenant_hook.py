"""End-to-end validation of the /callback tenant-id auto-assignment hook.

Walks the full happy path against the running dev stack:

  1. Patches the running Keycloak's `gatekeeper` client to enable
     serviceAccountsEnabled and grants `realm-management/manage-users` +
     `view-users` to its service account user. (The realm.json change
     only fires on a fresh `--import-realm`, which we won't force on
     the dev DB; this script is the runtime equivalent.)
  2. Creates a test user in the `app` realm WITHOUT a `tenant_id`
     attribute — exactly the shape a self-registered user has.
  3. Drives the OIDC Authorization Code flow as that user via the
     `tms-web` client (login form POST → 302 to /callback?code=...).
  4. Hits the gatekeeper's /callback with the code and asserts:
       - 302 response with cookies set
       - the `tenant_session` cookie's JWT carries `https://platform/tenant_id`
       - Keycloak now shows `tenant_id=<DEFAULT>` on the user
  5. Cleans up the test user.

Idempotent: re-running cleans up the test user up front.
"""

from __future__ import annotations

import json
import re
import sys
from urllib.parse import parse_qs, urlparse

import httpx

# ── Constants tied to the dev stack ───────────────────────────────────
KC_URL = "http://keycloak:9180"  # requires `keycloak → localhost` in hosts file
GATEKEEPER_URL = "http://localhost:80"  # via traefik
APP_REALM = "app"
GATEKEEPER_CLIENT_ID = "gatekeeper"
TMS_WEB_CLIENT_ID = "tms-web"
DEFAULT_TENANT = "00000000-0000-0000-0000-000000000001"
TENANT_CLAIM = "https://platform/tenant_id"

TEST_USERNAME = "tenant-hook-validate@local"
TEST_PASSWORD = "ValidatePass123!"

ADMIN_USER = "admin"
ADMIN_PASS = "admin"


def _ok(label: str, ok: bool, detail: str = "") -> None:
    mark = "[ok]" if ok else "[!!]"
    print(f"{mark} {label}{(' — ' + detail) if detail else ''}")
    if not ok:
        sys.exit(1)


def _admin_token() -> str:
    r = httpx.post(
        f"{KC_URL}/realms/master/protocol/openid-connect/token",
        data={
            "grant_type": "password",
            "client_id": "admin-cli",
            "username": ADMIN_USER,
            "password": ADMIN_PASS,
        },
        timeout=10,
    )
    r.raise_for_status()
    return r.json()["access_token"]


def _get_client_uuid(token: str, client_id: str) -> str:
    r = httpx.get(
        f"{KC_URL}/admin/realms/{APP_REALM}/clients",
        params={"clientId": client_id},
        headers={"Authorization": f"Bearer {token}"},
        timeout=10,
    )
    r.raise_for_status()
    items = r.json()
    if not items:
        raise SystemExit(f"client {client_id} not found in realm {APP_REALM}")
    return items[0]["id"]


def patch_tms_web_redirect(token: str, redirect_uri: str) -> None:
    """Add an explicit redirect URI to the tms-web client. Wildcard
    patterns like `http://*.localhost/*` aren't matched by Keycloak's
    redirect-URI validator, so register the literal value."""
    client_uuid = _get_client_uuid(token, TMS_WEB_CLIENT_ID)
    r = httpx.get(
        f"{KC_URL}/admin/realms/{APP_REALM}/clients/{client_uuid}",
        headers={"Authorization": f"Bearer {token}"},
        timeout=10,
    )
    r.raise_for_status()
    cfg = r.json()
    uris = list(cfg.get("redirectUris") or [])
    if redirect_uri not in uris:
        uris.append(redirect_uri)
        cfg["redirectUris"] = uris
        r = httpx.put(
            f"{KC_URL}/admin/realms/{APP_REALM}/clients/{client_uuid}",
            json=cfg,
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
        r.raise_for_status()
    _ok(f"tms-web redirectUris contains {redirect_uri}", True)


def patch_gatekeeper_client(token: str) -> None:
    """Enable service account on gatekeeper client and grant the
    `manage-users` and `view-users` realm-management roles."""
    client_uuid = _get_client_uuid(token, GATEKEEPER_CLIENT_ID)

    # 1. Flip serviceAccountsEnabled on.
    r = httpx.get(
        f"{KC_URL}/admin/realms/{APP_REALM}/clients/{client_uuid}",
        headers={"Authorization": f"Bearer {token}"},
        timeout=10,
    )
    r.raise_for_status()
    cfg = r.json()
    if not cfg.get("serviceAccountsEnabled"):
        cfg["serviceAccountsEnabled"] = True
        r = httpx.put(
            f"{KC_URL}/admin/realms/{APP_REALM}/clients/{client_uuid}",
            json=cfg,
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
        r.raise_for_status()
    _ok("gatekeeper client serviceAccountsEnabled=true", True)

    # 2. Find the service account user.
    r = httpx.get(
        f"{KC_URL}/admin/realms/{APP_REALM}/clients/{client_uuid}/service-account-user",
        headers={"Authorization": f"Bearer {token}"},
        timeout=10,
    )
    r.raise_for_status()
    sa_user_id = r.json()["id"]

    # 3. Look up the realm-management client and the role IDs we want.
    rm_uuid = _get_client_uuid(token, "realm-management")
    r = httpx.get(
        f"{KC_URL}/admin/realms/{APP_REALM}/clients/{rm_uuid}/roles",
        headers={"Authorization": f"Bearer {token}"},
        timeout=10,
    )
    r.raise_for_status()
    by_name = {role["name"]: role for role in r.json()}
    grants = [by_name[name] for name in ("manage-users", "view-users")]

    # 4. POST the role mappings (idempotent — already-granted roles are
    #    silently accepted).
    r = httpx.post(
        f"{KC_URL}/admin/realms/{APP_REALM}/users/{sa_user_id}/role-mappings/clients/{rm_uuid}",
        json=grants,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        timeout=10,
    )
    if r.status_code not in (204, 200):
        r.raise_for_status()
    _ok("granted manage-users + view-users to service-account-gatekeeper", True)


def cleanup_test_user(token: str) -> None:
    r = httpx.get(
        f"{KC_URL}/admin/realms/{APP_REALM}/users",
        params={"username": TEST_USERNAME, "exact": "true"},
        headers={"Authorization": f"Bearer {token}"},
        timeout=10,
    )
    r.raise_for_status()
    for user in r.json():
        httpx.delete(
            f"{KC_URL}/admin/realms/{APP_REALM}/users/{user['id']}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )


def create_test_user_without_tenant(token: str) -> str:
    """Create a user with NO tenant_id attribute (mimics self-registration)."""
    cleanup_test_user(token)

    r = httpx.post(
        f"{KC_URL}/admin/realms/{APP_REALM}/users",
        json={
            "username": TEST_USERNAME,
            "email": TEST_USERNAME,
            "firstName": "Hook",
            "lastName": "Validate",
            "enabled": True,
            "emailVerified": True,
            "requiredActions": [],
            "credentials": [
                {
                    "type": "password",
                    "value": TEST_PASSWORD,
                    "temporary": False,
                }
            ],
        },
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        timeout=10,
    )
    if r.status_code not in (201, 204):
        r.raise_for_status()

    # Look up the new user's id.
    r = httpx.get(
        f"{KC_URL}/admin/realms/{APP_REALM}/users",
        params={"username": TEST_USERNAME, "exact": "true"},
        headers={"Authorization": f"Bearer {token}"},
        timeout=10,
    )
    r.raise_for_status()
    user = r.json()[0]
    assert "tenant_id" not in (user.get("attributes") or {}), (
        f"freshly-created user already has tenant_id: {user}"
    )
    _ok(
        "created test user without tenant_id",
        True,
        f"sub={user['id']} (attributes={user.get('attributes', {})})",
    )
    return user["id"]


def get_authorization_code(redirect_uri: str) -> str:
    """Drive the Keycloak login form to obtain an OIDC authorization code.

    Uses the `gatekeeper` (confidential) client because the gatekeeper's
    /callback exchanges the code with the gatekeeper client's credentials
    (`tc.client_id` from `get_fallback_config` resolves to GATEKEEPER_CLIENT_ID).
    Auth codes are bound to the issuing client, so initiating via the
    public `tms-web` client would produce codes the gatekeeper can't
    exchange."""
    with httpx.Client(timeout=15, follow_redirects=False) as c:
        # 1. Hit the auth endpoint to get a session cookie + login form HTML.
        r = c.get(
            f"{KC_URL}/realms/{APP_REALM}/protocol/openid-connect/auth",
            params={
                "client_id": GATEKEEPER_CLIENT_ID,
                "response_type": "code",
                "scope": "openid",
                "redirect_uri": redirect_uri,
                "state": "/dashboard",
            },
        )
        if r.status_code != 200:
            raise SystemExit(f"auth endpoint returned {r.status_code}: {r.text[:500]}")
        # 2. Find the form action URL.
        m = re.search(r'<form[^>]+action="([^"]+)"', r.text)
        if not m:
            raise SystemExit("could not find Keycloak login form action")
        action_url = m.group(1).replace("&amp;", "&")

        # 3. POST the credentials.
        r = c.post(
            action_url,
            data={"username": TEST_USERNAME, "password": TEST_PASSWORD},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        # Keycloak responds 302 with code= in the redirect URL.
        if r.status_code != 302:
            raise SystemExit(
                f"login form did not 302 (got {r.status_code}): {r.text[:200]}"
            )
        location = r.headers["location"]
        qs = parse_qs(urlparse(location).query)
        if "code" not in qs:
            raise SystemExit(f"no code in redirect: {location}")
        return qs["code"][0]


def call_callback(code: str) -> httpx.Response:
    """Hit the gatekeeper's /callback (via traefik) with the auth code.

    Connects to 127.0.0.1 directly (Windows doesn't auto-resolve
    `app.localhost`) and sets `Host: app.localhost` so traefik routes
    the request. Also sets X-Forwarded-Host explicitly so the gatekeeper
    sees the same hostname it would behind a real reverse proxy and
    rebuilds the redirect_uri identically to what was sent to Keycloak."""
    with httpx.Client(timeout=15, follow_redirects=False) as c:
        return c.get(
            "http://127.0.0.1/callback",
            params={"code": code, "state": "/dashboard"},
            headers={
                "Host": "app.localhost",
                "X-Forwarded-Host": "app.localhost",
                "X-Forwarded-Proto": "http",
            },
        )


def decode_jwt_no_verify(token: str) -> dict:
    import base64

    payload_b64 = token.split(".")[1]
    payload_b64 += "=" * ((4 - len(payload_b64) % 4) % 4)
    payload_b64 = payload_b64.replace("-", "+").replace("_", "/")
    return json.loads(base64.b64decode(payload_b64).decode())


def main() -> None:
    print("== Validating /callback tenant-id auto-assignment hook ==")

    admin = _admin_token()
    _ok("master admin token", True)

    redirect_uri = "http://app.localhost/callback"
    # gatekeeper client already accepts redirectUris=["*"], so no
    # tms-web patching needed.
    patch_gatekeeper_client(admin)
    user_id = create_test_user_without_tenant(admin)

    code = get_authorization_code(redirect_uri)
    _ok("obtained OIDC authorization code", True, f"code={code[:12]}…")

    resp = call_callback(code)
    _ok(
        "/callback returned 302 with cookies",
        resp.status_code == 302
        and any("tenant_session=" in c for c in resp.headers.get_list("set-cookie")),
        f"status={resp.status_code} body={resp.text[:300]!r} cookies={resp.headers.get_list('set-cookie')}",
    )

    # Pull the access-token JWT out of the Set-Cookie header.
    set_cookies = resp.headers.get_list("set-cookie")
    access_jwt = next(
        (
            c.split("tenant_session=", 1)[1].split(";")[0]
            for c in set_cookies
            if "tenant_session=" in c
        ),
        "",
    )
    if not access_jwt:
        raise SystemExit(f"no tenant_session cookie: {set_cookies}")
    claims = decode_jwt_no_verify(access_jwt)
    _ok(
        f"cookie JWT carries {TENANT_CLAIM}",
        claims.get(TENANT_CLAIM) == DEFAULT_TENANT,
        f"got={claims.get(TENANT_CLAIM)}",
    )

    # Verify Keycloak now shows the tenant_id attribute on the user.
    r = httpx.get(
        f"{KC_URL}/admin/realms/{APP_REALM}/users/{user_id}",
        headers={"Authorization": f"Bearer {admin}"},
        timeout=10,
    )
    r.raise_for_status()
    user = r.json()
    _ok(
        "Keycloak user now has tenant_id attribute",
        user.get("attributes", {}).get("tenant_id") == [DEFAULT_TENANT],
        f"attributes={user.get('attributes')}",
    )

    # Use the cookies to validate the JWT through gatekeeper's /auth
    # ForwardAuth interceptor — this is the path Traefik calls before
    # forwarding any /api/* request. It checks the cookie's JWT, the
    # tenant claim, and the rate limit, then returns the X-Gatekeeper-*
    # headers Traefik attaches to the upstream call. If /auth returns
    # 200, every backend with `AuthGuard` will accept the token.
    session_cookie = next(
        (
            c.split("tenant_session=", 1)[1].split(";")[0]
            for c in set_cookies
            if "tenant_session=" in c
        ),
        "",
    )
    with httpx.Client(timeout=15) as c:
        api = c.get(
            "http://127.0.0.1/auth/userinfo",
            headers={"Host": "app.localhost"},
            cookies={"tenant_session": session_cookie},
        )
    _ok(
        "gatekeeper /auth/userinfo accepts the new token",
        api.status_code == 200,
        f"status={api.status_code} body={api.text[:200]!r}",
    )
    profile = api.json() if api.status_code == 200 else {}
    _ok(
        "userinfo carries the new user's email",
        profile.get("email") == TEST_USERNAME,
        f"got={profile.get('email')}",
    )

    # Hit a real backend endpoint behind Traefik forward-auth to confirm
    # the issuer registered in `platform_auth.AuthGuard` matches the iss
    # Keycloak stamps. This is what the SPA loop actually trips on — if
    # the gatekeeper says 200 but profile says 401, the SPA bounces
    # through /auth/login again and the page reloads.
    with httpx.Client(timeout=15) as c:
        backend = c.get(
            "http://127.0.0.1/api/profile/v1/me/preferences",
            headers={"Host": "app.localhost"},
            cookies={"tenant_session": session_cookie},
        )
    _ok(
        "profile service accepts the new token",
        backend.status_code in (200, 404),  # 404 = no row yet, also fine
        f"status={backend.status_code} body={backend.text[:200]!r}",
    )

    cleanup_test_user(admin)
    _ok("cleaned up test user", True)
    print("\n== ALL CHECKS PASSED ==")


if __name__ == "__main__":
    main()
