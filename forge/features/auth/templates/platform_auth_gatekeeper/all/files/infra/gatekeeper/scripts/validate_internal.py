"""Internal validation: runs INSIDE a container on the app-network so
all calls go through `keycloak:8080`, sidestepping the dev-only
issuer-mismatch on token refresh that hits scripts running on the host.

Replicates `validate_tenant_hook.py` but with internal URLs throughout.
The realm patches (serviceAccountsEnabled, roles, unmanagedAttributePolicy)
must already be in place — this script only drives the user flow.
"""

from __future__ import annotations

import json
import re
import sys
from urllib.parse import parse_qs, urlparse

import httpx

KC_URL = "http://keycloak:8080"
GK_URL = "http://gatekeeper:5000"
APP_REALM = "app"
GATEKEEPER_CLIENT_ID = "gatekeeper"
DEFAULT_TENANT = "00000000-0000-0000-0000-000000000001"
TENANT_CLAIM = "https://platform/tenant_id"

TEST_USERNAME = "tenant-hook-internal@local"
TEST_PASSWORD = "ValidatePass123!"


def _ok(label: str, ok: bool, detail: str = "") -> None:
    mark = "[ok]" if ok else "[!!]"
    print(f"{mark} {label}{(' � ' + detail) if detail else ''}")
    if not ok:
        sys.exit(1)


def _admin_token() -> str:
    r = httpx.post(
        f"{KC_URL}/realms/master/protocol/openid-connect/token",
        data={
            "grant_type": "password",
            "client_id": "admin-cli",
            "username": "admin",
            "password": "admin",
        },
        timeout=10,
    )
    r.raise_for_status()
    return r.json()["access_token"]


def cleanup(token: str) -> None:
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


def create_user(token: str) -> str:
    cleanup(token)
    r = httpx.post(
        f"{KC_URL}/admin/realms/{APP_REALM}/users",
        json={
            "username": TEST_USERNAME,
            "email": TEST_USERNAME,
            "firstName": "Hook",
            "lastName": "Internal",
            "enabled": True,
            "emailVerified": True,
            "requiredActions": [],
            "credentials": [
                {"type": "password", "value": TEST_PASSWORD, "temporary": False}
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
    r = httpx.get(
        f"{KC_URL}/admin/realms/{APP_REALM}/users",
        params={"username": TEST_USERNAME, "exact": "true"},
        headers={"Authorization": f"Bearer {token}"},
        timeout=10,
    )
    r.raise_for_status()
    return r.json()[0]["id"]


def get_code(redirect_uri: str) -> str:
    with httpx.Client(timeout=15, follow_redirects=False) as c:
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
            raise SystemExit(f"auth endpoint {r.status_code}: {r.text[:300]}")
        m = re.search(r'<form[^>]+action="([^"]+)"', r.text)
        if not m:
            raise SystemExit("no form action")
        action_url = m.group(1).replace("&amp;", "&")
        r = c.post(
            action_url,
            data={"username": TEST_USERNAME, "password": TEST_PASSWORD},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if r.status_code != 302:
            raise SystemExit(f"login form {r.status_code}: {r.text[:300]}")
        qs = parse_qs(urlparse(r.headers["location"]).query)
        if "code" not in qs:
            raise SystemExit(f"no code in {r.headers['location']}")
        return qs["code"][0]


def hit_callback(code: str, redirect_uri: str) -> httpx.Response:
    """Hit gatekeeper's /callback directly on its internal port. Set
    Host = the redirect_uri's host so the gatekeeper rebuilds the same
    redirect_uri it would have during a real browser flow."""
    parsed = urlparse(redirect_uri)
    with httpx.Client(timeout=15, follow_redirects=False) as c:
        return c.get(
            f"{GK_URL}/callback",
            params={"code": code, "state": "/dashboard"},
            headers={
                "Host": parsed.netloc,
                "X-Forwarded-Host": parsed.netloc,
                "X-Forwarded-Proto": parsed.scheme,
            },
        )


def decode(token: str) -> dict:
    import base64

    p = token.split(".")[1]
    p += "=" * ((4 - len(p) % 4) % 4)
    p = p.replace("-", "+").replace("_", "/")
    return json.loads(base64.b64decode(p).decode())


def main() -> None:
    print("== Internal validation: /callback hook against keycloak:8080 ==")
    admin = _admin_token()
    _ok("master admin token", True)
    user_id = create_user(admin)
    _ok("created test user without tenant_id", True, f"sub={user_id}")

    # Use internal Keycloak URL as redirect_uri so the iss claim's host
    # (keycloak:8080) matches the URL the gatekeeper uses at refresh time.
    redirect_uri = "http://keycloak:8080/realms/app/account/"  # placeholder host
    # Actually the redirect_uri only needs to satisfy Keycloak's allowlist
    # for the gatekeeper client (which is ["*"]). The gatekeeper rebuilds
    # its own redirect_uri from the request's Host header for the token
    # exchange — so what matters is the Host header on /callback.
    redirect_uri = "http://app.localhost/callback"
    code = get_code(redirect_uri)
    _ok("obtained auth code", True, f"code={code[:12]}…")

    resp = hit_callback(code, redirect_uri)
    _ok(
        "/callback returned 302",
        resp.status_code == 302,
        f"status={resp.status_code} body={resp.text[:200]!r}",
    )

    cookies = resp.headers.get_list("set-cookie")
    access_jwt = next(
        (
            c.split("tenant_session=", 1)[1].split(";")[0]
            for c in cookies
            if "tenant_session=" in c
        ),
        "",
    )
    _ok("tenant_session cookie present", bool(access_jwt))
    claims = decode(access_jwt)
    _ok(
        f"cookie JWT has {TENANT_CLAIM}={DEFAULT_TENANT}",
        claims.get(TENANT_CLAIM) == DEFAULT_TENANT,
        f"got={claims.get(TENANT_CLAIM)}",
    )

    r = httpx.get(
        f"{KC_URL}/admin/realms/{APP_REALM}/users/{user_id}",
        headers={"Authorization": f"Bearer {admin}"},
        timeout=10,
    )
    r.raise_for_status()
    user = r.json()
    _ok(
        "Keycloak user has tenant_id attribute",
        user.get("attributes", {}).get("tenant_id") == [DEFAULT_TENANT],
        f"attributes={user.get('attributes')}",
    )

    cleanup(admin)
    _ok("cleaned up", True)
    print("\n== ALL INTERNAL CHECKS PASSED ==")


if __name__ == "__main__":
    main()
