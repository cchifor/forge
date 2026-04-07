# src/app/gatekeeper/helpers.py
"""
Shared helpers used across the Gatekeeper routes.
"""

from __future__ import annotations

import logging
import urllib.parse
from typing import TypedDict

from fastapi import Response

from app.gatekeeper.config import get_settings


class RealmAccess(TypedDict, total=False):
    roles: list[str]


class JWTPayload(TypedDict, total=False):
    """Shape of the decoded Keycloak JWT access token."""

    sub: str
    email: str
    aud: str
    exp: int
    realm_access: RealmAccess

logger = logging.getLogger(__name__)


# ── Tenant extraction ──────────────────────────────────────────────────────


def extract_tenant(forwarded_host: str | None, host: str | None = None) -> str:
    """
    Derive the tenant ID from the ``X-Forwarded-Host`` (preferred) or
    ``Host`` header.

    Strategy: take the *first* subdomain label.
    ``tenantA.example.com`` → ``tenantA``

    Raises
    ------
    ValueError
        When no usable host header is present.
    """
    raw = forwarded_host or host
    if not raw:
        raise ValueError("Cannot resolve tenant: no Host or X-Forwarded-Host header")

    # Strip port if present (e.g. "tenantA.example.com:8080")
    hostname = raw.split(":")[0]
    parts = hostname.split(".")

    if len(parts) < 2:
        # Single-label hostname (e.g. "localhost") — treat whole name as tenant
        return hostname

    return parts[0]


# ── Login URL construction ─────────────────────────────────────────────────


def build_login_url(
    tenant: str,
    redirect_uri: str,
    state: str,
    *,
    issuer_url: str | None = None,
    client_id: str | None = None,
) -> str:
    """
    Construct the Keycloak Authorization Endpoint URL for the given tenant.

    Parameters
    ----------
    tenant:
        Realm slug.
    redirect_uri:
        The ``/callback`` URL the user should be sent back to.
    state:
        Opaque value forwarded through the OIDC flow — we use the
        originally-requested URI so we can redirect back after login.
    issuer_url:
        Per-tenant issuer URL from TMS.  Falls back to static config.
    client_id:
        Per-tenant OIDC client ID.  Falls back to static config.
    """
    cfg = get_settings()
    base_url = issuer_url or f"{cfg.keycloak_base_url}/{tenant}"
    cid = client_id or cfg.gatekeeper_client_id
    base = f"{base_url}/protocol/openid-connect/auth"
    params = urllib.parse.urlencode(
        {
            "response_type": "code",
            "client_id": cid,
            "redirect_uri": redirect_uri,
            "scope": "openid email profile",
            "state": state,
        }
    )
    return f"{base}?{params}"


def build_logout_url(tenant: str, *, issuer_url: str | None = None) -> str:
    """
    Construct the Keycloak end-session endpoint URL for the given tenant.
    """
    cfg = get_settings()
    base_url = issuer_url or f"{cfg.keycloak_base_url}/{tenant}"
    return f"{base_url}/protocol/openid-connect/logout"


# ── Response builders ──────────────────────────────────────────────────────


def create_success_response(
    payload: JWTPayload,
    tenant: str,
    *,
    new_access_token: str | None = None,
    new_refresh_token: str | None = None,
    extra_headers: dict[str, str] | None = None,
) -> Response:
    """
    Build the HTTP 200 response returned to Traefik on successful
    authentication.

    Injects identity + RBAC headers so downstream services never need
    to parse a JWT themselves.

    If *new_access_token* / *new_refresh_token* are provided (token-refresh
    scenario), the corresponding ``Set-Cookie`` headers are attached so
    Traefik forwards them to the browser transparently.
    """
    cfg = get_settings()
    response = Response(status_code=200)

    # ── Standard identity headers ───────────────────────────────────────
    response.headers["X-Gatekeeper-User-Id"] = payload.get("sub", "")
    response.headers["X-Gatekeeper-Email"] = payload.get("email", "")
    response.headers["X-Gatekeeper-Tenant"] = tenant

    # ── RBAC extraction ─────────────────────────────────────────────────
    realm_access = payload.get("realm_access", {})
    roles: list[str] = realm_access.get("roles", [])
    clean_roles = [r for r in roles if not r.startswith("default-roles")]
    response.headers["X-Gatekeeper-Roles"] = ",".join(clean_roles)

    # ── Token refresh cookies (if applicable) ───────────────────────────
    if new_access_token:
        _set_token_cookie(
            response,
            name=cfg.cookie_name,
            value=new_access_token,
        )
    if new_refresh_token:
        _set_token_cookie(
            response,
            name=cfg.refresh_cookie_name,
            value=new_refresh_token,
        )

    # ── Extra headers (e.g. rate-limit) ─────────────────────────────────
    if extra_headers:
        for key, value in extra_headers.items():
            response.headers[key] = value

    return response


def create_machine_success_response(
    *,
    user_id: str,
    email: str,
    tenant: str,
    roles: list[str],
    extra_headers: dict[str, str] | None = None,
) -> Response:
    """
    Build the HTTP 200 response for a machine (API-key) authentication.

    Produces the **exact same** ``X-Gatekeeper-*`` headers as the human
    track so downstream services are completely agnostic.
    """
    response = Response(status_code=200)

    response.headers["X-Gatekeeper-User-Id"] = user_id
    response.headers["X-Gatekeeper-Email"] = email
    response.headers["X-Gatekeeper-Tenant"] = tenant
    response.headers["X-Gatekeeper-Roles"] = ",".join(roles)
    response.headers["X-Gatekeeper-Auth-Method"] = "api-key"

    if extra_headers:
        for key, value in extra_headers.items():
            response.headers[key] = value

    return response


def _set_token_cookie(
    response: Response,
    *,
    name: str,
    value: str,
    max_age: int | None = None,
) -> None:
    """Append a ``Set-Cookie`` header with secure defaults."""
    cfg = get_settings()
    response.set_cookie(
        key=name,
        value=value,
        httponly=True,
        samesite="lax",
        secure=cfg.cookie_secure,
        path="/",
        max_age=max_age,
    )


def _delete_token_cookie(response: Response, *, name: str) -> None:
    """Expire a token cookie with the same security attributes as :func:`_set_token_cookie`."""
    cfg = get_settings()
    response.delete_cookie(
        key=name,
        path="/",
        httponly=True,
        samesite="lax",
        secure=cfg.cookie_secure,
    )


def validate_state(state: str | None) -> str:
    """
    Guard against open-redirect attacks on ``/callback``.

    ``state`` must be a **relative** path (starts with ``/``).
    Falls back to ``"/"`` when invalid or missing.
    """
    if not state or not state.startswith("/") or state.startswith("//"):
        logger.warning(
            "Invalid or missing state parameter (%r) — defaulting to '/'",
            state,
        )
        return "/"
    return state
