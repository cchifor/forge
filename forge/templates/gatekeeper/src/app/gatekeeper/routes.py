# src/app/gatekeeper/routes.py
"""
FastAPI router that exposes the three Gatekeeper endpoints:

* ``GET /auth``      — Traefik ForwardAuth interceptor
* ``GET /callback``  — OIDC Authorization Code exchange
* ``GET /logout``    — Session termination
"""

from __future__ import annotations

import logging

import httpx
import jwt
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

import hmac

from app.gatekeeper.apikeys import validate_api_key
from app.gatekeeper.config import get_settings
from app.gatekeeper.helpers import (
    _delete_token_cookie,
    _set_token_cookie,
    build_login_url,
    build_logout_url,
    create_machine_success_response,
    create_success_response,
    extract_tenant,
    validate_state,
)
from app.gatekeeper.jwks import verify_token
from app.gatekeeper.metrics import RATE_LIMIT_REJECTIONS, AuthMetricsRecorder
from app.gatekeeper.oidc import exchange_code, refresh_tokens
from app.gatekeeper.ratelimit import enforce_rate_limit, get_tenant_quota
from app.gatekeeper.tenant_config import (
    TenantConfig,
    get_fallback_config,
    resolve_tenant_config,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["gatekeeper"])


# ── GET /metrics ────────────────────────────────────────────────────────────


@router.get("/metrics", include_in_schema=False)
async def metrics() -> Response:
    """Prometheus scrape target — returns all registered metrics."""
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


# ── GET /auth ───────────────────────────────────────────────────────────────


async def _check_rate_limit(
    tenant: str,
    default_limit: int,
    metrics: AuthMetricsRecorder,
) -> dict[str, str]:
    """Enforce tenant rate-limit; record metrics and re-raise on 429."""
    try:
        quota = await get_tenant_quota(tenant, default_limit)
        return await enforce_rate_limit(tenant, quota)
    except HTTPException:
        metrics.record("rate_limited")
        RATE_LIMIT_REJECTIONS.labels(tenant_id=tenant).inc()
        raise


@router.get("/auth")
async def auth(request: Request) -> Response:
    """
    Traefik ForwardAuth target — **dual-track** authentication.

    **Track 1 — Machine (API key):** When the ``X-API-Key`` header is
    present the Gatekeeper validates the key against Redis (SHA-256 lookup),
    skipping Keycloak entirely.

    **Track 2 — Human (OIDC / JWT):** Falls back to cookie-based JWT
    validation against Keycloak, including silent token refresh when the
    access token is expired but a valid refresh token cookie exists.

    Both tracks inject the **same** ``X-Gatekeeper-*`` identity headers
    so downstream services are auth-method-agnostic.

    After successful authentication, tenant-level rate limiting is enforced
    via a Redis fixed-window counter.
    """
    cfg = get_settings()

    # 1. Resolve tenant
    forwarded_host = request.headers.get("x-forwarded-host")
    try:
        tenant = extract_tenant(forwarded_host, request.headers.get("host"))
    except ValueError:
        return Response(status_code=400, content="Missing host information")

    metrics = AuthMetricsRecorder(tenant)

    # 1b. Resolve per-tenant OIDC config (Redis cache → fallback to static)
    hostname = forwarded_host or request.headers.get("host", "")
    tc = await resolve_tenant_config(hostname)
    if tc is None:
        tc = get_fallback_config(tenant)

    # ================================================================
    # TRACK 1: MACHINE AUTHENTICATION (API KEY)
    # ================================================================
    api_key = request.headers.get("x-api-key")
    if api_key:
        metrics.method = "api_key"
        record = await validate_api_key(api_key)

        if not record or record.tenant_id != tenant:
            metrics.record("invalid_key")
            return Response(status_code=401, content="Invalid API Key")

        rate_headers = await _check_rate_limit(tenant, tc.rate_limit, metrics)
        metrics.record("success")
        return create_machine_success_response(
            user_id=record.owner,
            email=f"{record.name}@api-key",
            tenant=tenant,
            roles=record.roles,
            extra_headers={
                **rate_headers,
                "X-Gatekeeper-Realm-Type": tc.realm_type,
            },
        )

    # ================================================================
    # TRACK 1.5: TEST BYPASS (sentinel / dev-test environments only)
    # ================================================================
    if cfg.test_bypass_enabled and cfg.test_bypass_token:
        test_token = request.headers.get("x-test-token")
        if test_token:
            metrics.method = "test_bypass"
            allowed_tenants = [
                t.strip()
                for t in cfg.test_bypass_tenant_ids.split(",")
                if t.strip()
            ]
            if (
                hmac.compare_digest(test_token, cfg.test_bypass_token)
                and tenant in allowed_tenants
            ):
                rate_headers = await _check_rate_limit(
                    tenant, tc.rate_limit, metrics
                )
                metrics.record("success")
                return create_machine_success_response(
                    user_id="sentinel-test-runner",
                    email="sentinel@internal.test",
                    tenant=tenant,
                    roles=["tester"],
                    extra_headers={
                        **rate_headers,
                        "X-Gatekeeper-Auth-Method": "test-bypass",
                    },
                )
            metrics.record("invalid_key")
            return Response(status_code=401, content="Invalid test bypass token")

    # ================================================================
    # TRACK 2: HUMAN AUTHENTICATION (OIDC / JWT)
    # ================================================================
    metrics.method = "jwt"

    # 2. Read cookies
    access_token = request.cookies.get(cfg.cookie_name)
    refresh_token_cookie = request.cookies.get(cfg.refresh_cookie_name)

    # No access token at all → redirect to login
    if not access_token:
        metrics.method = "none"
        metrics.record("redirected")
        return _redirect_to_login(request, tenant, forwarded_host, tc=tc)

    # 3. Validate JWT
    try:
        payload = await verify_token(
            access_token, tenant,
            issuer_url=tc.issuer_url, client_id=tc.client_id,
        )
        rate_headers = await _check_rate_limit(tenant, tc.rate_limit, metrics)
        metrics.record("success")
        return create_success_response(
            payload, tenant,
            extra_headers={**rate_headers, "X-Gatekeeper-Realm-Type": tc.realm_type},
        )

    except jwt.ExpiredSignatureError:
        # ── Token refresh flow ──────────────────────────────────────────
        if not refresh_token_cookie:
            logger.debug(
                "Access token expired and no refresh token — redirect to login"
            )
            metrics.record("redirected")
            return _redirect_to_login(request, tenant, forwarded_host, tc=tc)

        try:
            token_data = await refresh_tokens(
                tenant, refresh_token_cookie,
                issuer_url=tc.issuer_url,
                client_id=tc.client_id,
                client_secret=tc.client_secret,
            )
            new_access = token_data["access_token"]
            new_refresh = token_data.get("refresh_token", refresh_token_cookie)

            payload = await verify_token(
                new_access, tenant,
                issuer_url=tc.issuer_url, client_id=tc.client_id,
            )
            rate_headers = await _check_rate_limit(
                tenant, tc.rate_limit, metrics
            )
            metrics.record("expired_refreshed")
            return create_success_response(
                payload,
                tenant,
                new_access_token=new_access,
                new_refresh_token=new_refresh,
                extra_headers={
                    **rate_headers,
                    "X-Gatekeeper-Realm-Type": tc.realm_type,
                },
            )
        except (httpx.HTTPStatusError, jwt.InvalidTokenError, KeyError) as exc:
            logger.warning("Token refresh failed: %s", exc)
            metrics.record("failed")
            return _redirect_to_login(request, tenant, forwarded_host, tc=tc)

    except jwt.InvalidTokenError as exc:
        logger.warning("JWT validation failed for tenant=%s: %s", tenant, exc)
        metrics.record("failed")
        return _redirect_to_login(request, tenant, forwarded_host, tc=tc)


def _redirect_to_login(
    request: Request,
    tenant: str,
    forwarded_host: str | None,
    *,
    tc: TenantConfig | None = None,
) -> RedirectResponse:
    """Build a 302 redirect to the Keycloak login page for *tenant*."""
    # The callback must be reachable from the browser, so use the forwarded host
    scheme = request.headers.get("x-forwarded-proto", "http")
    host = forwarded_host or request.headers.get("host", "localhost")
    redirect_uri = f"{scheme}://{host}/callback"

    # Preserve the originally-requested URI as ``state``
    original_uri = request.headers.get("x-forwarded-uri", "/")

    login_url = build_login_url(
        tenant,
        redirect_uri,
        state=original_uri,
        issuer_url=tc.issuer_url if tc else None,
        client_id=tc.client_id if tc else None,
    )
    return RedirectResponse(url=login_url, status_code=302)


# ── GET /callback ───────────────────────────────────────────────────────────


@router.get("/callback")
async def callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
) -> Response:
    """
    OIDC Authorization Code callback.

    Keycloak redirects the user here after a successful login.  We exchange
    the ``code`` for tokens, set them as HttpOnly cookies, and redirect the
    user back to their original page (via ``state``).
    """
    cfg = get_settings()

    if not code:
        return Response(status_code=400, content="Missing authorization code")

    # 1. Resolve tenant
    forwarded_host = request.headers.get("x-forwarded-host")
    host_header = request.headers.get("host")
    try:
        tenant = extract_tenant(forwarded_host, host_header)
    except ValueError:
        return Response(status_code=400, content="Missing host information")

    # 2. Validate state (open-redirect protection)
    safe_state = validate_state(state)

    # 3. Build the redirect_uri that matches what we sent to Keycloak
    scheme = request.headers.get("x-forwarded-proto", "http")
    host = forwarded_host or host_header or "localhost"
    redirect_uri = f"{scheme}://{host}/callback"

    # 3b. Resolve per-tenant OIDC config
    tc = await resolve_tenant_config(forwarded_host or host_header or "")
    if tc is None:
        tc = get_fallback_config(tenant)

    # 4. Exchange code for tokens
    try:
        token_data = await exchange_code(
            tenant, code, redirect_uri,
            issuer_url=tc.issuer_url,
            client_id=tc.client_id,
            client_secret=tc.client_secret,
        )
    except httpx.HTTPStatusError as exc:
        logger.error("Token exchange failed: %s", exc)
        return Response(status_code=502, content="Token exchange with IdP failed")

    access_token = token_data.get("access_token", "")
    refresh_token = token_data.get("refresh_token", "")

    # 5. Build redirect response with cookies
    response = RedirectResponse(url=safe_state, status_code=302)
    _set_token_cookie(response, name=cfg.cookie_name, value=access_token)
    _set_token_cookie(response, name=cfg.refresh_cookie_name, value=refresh_token)

    return response


# ── GET /logout ─────────────────────────────────────────────────────────────


@router.get("/logout")
async def logout(request: Request) -> Response:
    """
    Terminate the session.

    Expires both the access-token and refresh-token cookies and redirects
    the browser to Keycloak's end-session endpoint for the tenant so
    the Keycloak session is destroyed as well.
    """
    cfg = get_settings()

    # 1. Resolve tenant
    forwarded_host = request.headers.get("x-forwarded-host")
    try:
        tenant = extract_tenant(forwarded_host, request.headers.get("host"))
    except ValueError:
        return Response(status_code=400, content="Missing host information")

    # 1b. Resolve per-tenant OIDC config
    tc = await resolve_tenant_config(forwarded_host or request.headers.get("host", ""))
    if tc is None:
        tc = get_fallback_config(tenant)

    # 2. Build Keycloak logout URL
    logout_url = build_logout_url(tenant, issuer_url=tc.issuer_url)

    # 3. Expire cookies and redirect
    response = RedirectResponse(url=logout_url, status_code=302)
    _delete_token_cookie(response, name=cfg.cookie_name)
    _delete_token_cookie(response, name=cfg.refresh_cookie_name)

    return response
