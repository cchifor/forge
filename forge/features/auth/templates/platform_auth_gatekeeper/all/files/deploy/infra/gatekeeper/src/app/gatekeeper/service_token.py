# src/app/gatekeeper/service_token.py
"""``POST /auth/token`` — OAuth2 token endpoint for service-to-service auth.

Standards: RFC 6749 §3.2 / §4.4 (``client_credentials`` grant) and RFC 8693
(``urn:ietf:params:oauth:grant-type:token-exchange``).

The endpoint is the second mint path on gatekeeper alongside the ForwardAuth
``/auth`` route (which handles UI traffic). Both produce the same internal
JWT shape — ``iss=http://gatekeeper:5000``, ``aud=platform-services``,
ES256 — so backends keep a single trust anchor.

Two grants:

* **client_credentials** — service acting for a tenant, no user. Mints a
  token with ``sub=<client_id>``, ``azp=<client_id>``, no ``act`` chain;
  scopes drawn from the registry; tenant from the request param.
* **token-exchange** — service acting on behalf of a user. Mints a token
  preserving the user's ``sub`` and ``tenant_id`` from a ``subject_token``,
  with ``azp=<client_id>`` and an ``act`` chain recording the service.
  Effective scopes = registry ∩ subject_token ∩ optional client request.

Verifier and registry are pluggable via :func:`build_verifier`; both come
off ``app.state``. Internal-token mint reuses the existing per-jti cache
so repeat requests for the same (client, tenant, subject) hit warm.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any
from urllib.parse import urlparse

import jwt as pyjwt
from fastapi import APIRouter, Form, Request
from fastapi.responses import JSONResponse

from app.gatekeeper.config import get_settings
from app.gatekeeper.delegation_grant import (
    DEFAULT_GRANT_TTL_SECONDS,
    DelegationGrantError,
    DelegationGrantStore,
)
from app.gatekeeper.internal_token import (
    EMAIL_CLAIM,
    TENANT_ID_CLAIM,
    TENANT_SLUG_CLAIM,
    mint_internal_token,
)
from app.gatekeeper.scopes import scopes_intersection, split_scope_string
from app.gatekeeper.service_registry import ServiceRegistry
from app.gatekeeper.service_verifier import (
    ClientAuthError,
    ClientCredentialVerifier,
)

logger = logging.getLogger(__name__)


router = APIRouter(tags=["gatekeeper-service-token"])


GRANT_CLIENT_CREDENTIALS = "client_credentials"
GRANT_TOKEN_EXCHANGE = "urn:ietf:params:oauth:grant-type:token-exchange"
TOKEN_TYPE_ACCESS_TOKEN = "urn:ietf:params:oauth:token-type:access_token"


def _error(
    status: int,
    code: str,
    description: str,
) -> JSONResponse:
    """RFC 6749 §5.2 token-endpoint error response shape."""
    return JSONResponse(
        status_code=status,
        content={"error": code, "error_description": description},
    )


def _success(
    *,
    access_token: str,
    expires_in: int,
    scope: str,
) -> JSONResponse:
    """RFC 6749 §5.1 token-endpoint success response shape."""
    return JSONResponse(
        content={
            "access_token": access_token,
            "token_type": "Bearer",
            "expires_in": expires_in,
            "scope": scope,
            "issued_token_type": TOKEN_TYPE_ACCESS_TOKEN,
        }
    )


def _state(request: Request) -> tuple[ClientCredentialVerifier, ServiceRegistry]:
    """Pull verifier + registry from app.state, with explicit failure on miswiring."""
    verifier = getattr(request.app.state, "service_verifier", None)
    registry = getattr(request.app.state, "service_registry", None)
    if verifier is None or registry is None:
        raise RuntimeError(
            "service-token endpoint hit before verifier/registry were "
            "initialised — check lifecycle.py wiring"
        )
    return verifier, registry


@router.post("/auth/token", include_in_schema=False)
async def auth_token(
    request: Request,
    grant_type: str = Form(...),
    client_id: str = Form(...),
    client_secret: str | None = Form(default=None),
    audience: str = Form(...),
    scope: str | None = Form(default=None),
    # client_credentials extension:
    tenant_id: str | None = Form(default=None),
    # token-exchange extension:
    subject_token: str | None = Form(default=None),
    subject_token_type: str | None = Form(default=None),
) -> JSONResponse:
    """Mint a gatekeeper-internal JWT for a service caller.

    Both branches end at :func:`mint_internal_token` so the resulting JWT
    is shape-identical to what UI traffic produces — backends don't care
    which grant created it.
    """
    verifier, registry = _state(request)

    # Step 1 — authenticate the caller.
    try:
        verified = await verifier.verify(
            client_id=client_id,
            client_secret=client_secret,
            request=request,
        )
    except ClientAuthError as exc:
        status = 403 if exc.error_code == "unauthorized_client" else 401
        return _error(status, exc.error_code, str(exc))

    # Step 2 — registry lookup. If the caller is verified but absent from
    # the registry the verifier should already have rejected — defensive.
    entry = registry.lookup(verified.client_id)
    if entry is None:
        return _error(401, "invalid_client", "client not registered")

    # Step 3 — audience must be in the caller's allowed list.
    if audience not in entry.audiences:
        return _error(
            403,
            "unauthorized_client",
            f"client {verified.client_id!r} not allowed for audience {audience!r}",
        )

    # Step 4 — dispatch on grant_type.
    if grant_type == GRANT_CLIENT_CREDENTIALS:
        return await _mint_client_credentials(
            request=request,
            entry=entry,
            audience=audience,
            tenant_id=tenant_id,
            requested_scope=scope,
        )
    if grant_type == GRANT_TOKEN_EXCHANGE:
        return await _mint_token_exchange(
            request=request,
            entry=entry,
            audience=audience,
            requested_scope=scope,
            subject_token=subject_token,
            subject_token_type=subject_token_type,
        )
    return _error(
        400,
        "unsupported_grant_type",
        f"grant_type {grant_type!r} not supported",
    )


async def _mint_client_credentials(
    *,
    request: Request,
    entry: Any,  # ServiceClient — quoted to avoid circular ref in type hints
    audience: str,
    tenant_id: str | None,
    requested_scope: str | None,
) -> JSONResponse:
    """RFC 6749 §4.4 — server-account acting on behalf of a tenant."""
    if not tenant_id:
        return _error(
            400,
            "invalid_request",
            "tenant_id required for client_credentials grant",
        )

    allowed = entry.allowed_scopes_for(audience)
    requested = split_scope_string(requested_scope) if requested_scope else None
    effective = scopes_intersection(allowed, requested)
    if requested is not None and not effective:
        # Client asked for scopes; none survived the intersection.
        return _error(
            400,
            "invalid_scope",
            "requested scopes are not granted to this client for this audience",
        )

    cfg = get_settings()
    payload = _synthetic_service_payload(
        client_id=entry.client_id,
        tenant_id=tenant_id,
        scopes=effective,
        target_service=audience,
    )
    # Mint with the platform-wide audience, NOT the per-service ``audience``
    # form param. Phase 4's invariant is one audience for every backend
    # (``cfg.internal_token_audience``); the request's ``audience`` names
    # the *target service* and drives registry/scope lookup. It's recorded
    # on the token's ``platform_target_service`` claim for audit only.
    token, exp = mint_internal_token(
        keycloak_payload=payload,
        key_ring=request.app.state.key_ring,
        issuer=cfg.gatekeeper_issuer,
        audience=cfg.internal_token_audience,
        ttl_seconds=cfg.internal_token_ttl_seconds,
        auth_method="cookie",  # not user-facing; "cookie" is the closest
    )
    expires_in = max(0, exp - int(time.time()))
    logger.info(
        "service_token_minted grant=client_credentials client_id=%s target=%s tenant=%s scopes=%d",
        entry.client_id,
        audience,
        tenant_id,
        len(effective),
    )
    return _success(
        access_token=token,
        expires_in=expires_in,
        scope=" ".join(sorted(effective)),
    )


async def _mint_token_exchange(
    *,
    request: Request,
    entry: Any,  # ServiceClient
    audience: str,
    requested_scope: str | None,
    subject_token: str | None,
    subject_token_type: str | None,
) -> JSONResponse:
    """RFC 8693 — service acting on behalf of an inbound user.

    The minted token preserves the user's ``sub`` and ``tenant_id`` and
    adds ``azp=<client_id>`` plus an ``act`` chain naming the calling
    service. Scope is the three-way intersection of registry, user
    token, and any client-requested subset.
    """
    if not subject_token:
        return _error(400, "invalid_request", "subject_token required")
    if subject_token_type and subject_token_type != TOKEN_TYPE_ACCESS_TOKEN:
        return _error(
            400,
            "invalid_request",
            f"subject_token_type {subject_token_type!r} not supported",
        )
    if not entry.may_act_for(audience):
        return _error(
            403,
            "unauthorized_client",
            f"client {entry.client_id!r} not authorized to act for audience {audience!r}",
        )

    # Verify subject_token. We only accept gatekeeper-issued tokens here:
    # the upstream user identity has already been laundered through
    # ``/auth`` so this is the canonical user shape.
    cfg = get_settings()
    try:
        subject_claims = _verify_gatekeeper_token(
            subject_token,
            request=request,
            issuer=cfg.gatekeeper_issuer,
            audience=cfg.internal_token_audience,
        )
    except _SubjectTokenError as exc:
        return _error(400, "invalid_grant", str(exc))

    user_scopes = (
        frozenset(split_scope_string(subject_claims.get("scope", "")))
        if subject_claims.get("scope")
        else frozenset()
    )
    allowed = entry.allowed_scopes_for(audience)
    requested = split_scope_string(requested_scope) if requested_scope else None
    candidate = scopes_intersection(allowed, requested)
    effective = scopes_intersection(candidate, user_scopes)
    if not effective:
        return _error(
            400,
            "invalid_scope",
            "no scopes survive (registry ∩ subject_token ∩ requested)",
        )

    payload = _delegated_user_payload(
        subject_claims=subject_claims,
        actor_client_id=entry.client_id,
        scopes=effective,
        target_service=audience,
    )
    token, exp = mint_internal_token(
        keycloak_payload=payload,
        key_ring=request.app.state.key_ring,
        issuer=cfg.gatekeeper_issuer,
        audience=cfg.internal_token_audience,
        ttl_seconds=cfg.internal_token_ttl_seconds,
        auth_method="cookie",
    )
    expires_in = max(0, exp - int(time.time()))
    logger.info(
        "service_token_minted grant=token_exchange client_id=%s target=%s sub=%s scopes=%d",
        entry.client_id,
        audience,
        subject_claims.get("sub"),
        len(effective),
    )
    return _success(
        access_token=token,
        expires_in=expires_in,
        scope=" ".join(sorted(effective)),
    )


def _synthetic_service_payload(
    *,
    client_id: str,
    tenant_id: str,
    scopes: frozenset[str],
    target_service: str,
) -> dict[str, Any]:
    """Build the keycloak-shaped payload for a server-account mint.

    ``mint_internal_token`` consumes a Keycloak access-token-shaped dict;
    we synthesize one with ``sub=<client_id>``, the requested tenant, the
    scope string, and an ``azp`` so backends can detect a service-account
    token. ``platform_target_service`` records the intended downstream
    for audit (the JWT's ``aud`` is always the platform-wide constant).
    """
    now = int(time.time())
    return {
        "sub": client_id,
        "iss": "gatekeeper-service-token",
        # ``aud`` here is just the input claim consumed by mint_internal_token;
        # the mint output overrides it with cfg.internal_token_audience.
        "aud": "gatekeeper-service-token",
        "iat": now,
        # Keycloak-style exp; mint clamps to its own ttl.
        "exp": now + 3600,
        "jti": f"svc:{client_id}:{uuid.uuid4()}",
        "azp": client_id,
        "platform_target_service": target_service,
        TENANT_ID_CLAIM: tenant_id,
        EMAIL_CLAIM: f"{client_id}@platform",
        "scope": " ".join(sorted(scopes)),
    }


def _delegated_user_payload(
    *,
    subject_claims: dict[str, Any],
    actor_client_id: str,
    scopes: frozenset[str],
    target_service: str,
) -> dict[str, Any]:
    """Build the keycloak-shaped payload for a token-exchange mint.

    Preserve ``sub``, tenant claims, email, and any roles from the user's
    subject_token. Override ``azp`` with the actor service. Add an
    ``act`` chain (RFC 8693 §2.2) so backends can trace the delegation.
    """
    now = int(time.time())
    payload: dict[str, Any] = {
        "sub": subject_claims["sub"],
        "iss": "gatekeeper-service-token",
        "aud": "gatekeeper-service-token",  # mint overrides this
        "iat": now,
        "exp": now + 3600,  # mint clamps
        "jti": f"obo:{actor_client_id}:{uuid.uuid4()}",
        "azp": actor_client_id,
        "platform_target_service": target_service,
        "scope": " ".join(sorted(scopes)),
        "act": {"sub": actor_client_id, "azp": actor_client_id},
    }
    # Copy identity claims through verbatim — mint_internal_token reads
    # them on this exact key set.
    if tid := subject_claims.get(TENANT_ID_CLAIM):
        payload[TENANT_ID_CLAIM] = tid
    if slug := subject_claims.get(TENANT_SLUG_CLAIM):
        payload[TENANT_SLUG_CLAIM] = slug
    if email := subject_claims.get(EMAIL_CLAIM) or subject_claims.get("email"):
        payload["email"] = email
    if realm := subject_claims.get("realm_access"):
        payload["realm_access"] = realm
    return payload


# ── subject_token verification ────────────────────────────────────────────


class _SubjectTokenError(Exception):
    """Raised when the inbound ``subject_token`` cannot be accepted."""


def _verify_gatekeeper_token(
    token: str,
    *,
    request: Request,
    issuer: str,
    audience: str,
) -> dict[str, Any]:
    """Verify a gatekeeper-issued JWT against the local KeyRing.

    We expect ``subject_token`` to be a token gatekeeper itself minted
    earlier (typically a user's session token forwarded by the calling
    service). Verification here mirrors what ``platform_auth.AuthGuard``
    does for inbound traffic — same algorithm, same JWKS — but inline,
    since we don't want to spin up a JWKSCache pointing at our own host.
    """
    key_ring = getattr(request.app.state, "key_ring", None)
    if key_ring is None:
        raise _SubjectTokenError("key ring unavailable")

    try:
        unverified = pyjwt.get_unverified_header(token)
    except pyjwt.InvalidTokenError as exc:
        raise _SubjectTokenError(f"subject_token unparseable: {exc}") from exc
    kid = unverified.get("kid")
    if not isinstance(kid, str) or not kid:
        raise _SubjectTokenError("subject_token missing kid header")
    alg = unverified.get("alg")
    if alg != "ES256":
        raise _SubjectTokenError(f"subject_token alg {alg!r} not accepted")

    jwk_dict = _find_jwk(key_ring, kid)
    if jwk_dict is None:
        raise _SubjectTokenError(f"subject_token kid {kid!r} not found in JWKS")

    try:
        public_key = pyjwt.algorithms.ECAlgorithm.from_jwk(jwk_dict)
        claims = pyjwt.decode(
            token,
            public_key,
            algorithms=["ES256"],
            audience=audience,
            issuer=issuer,
            options={"require": ["exp", "iat", "sub", "iss", "aud", "jti"]},
        )
    except pyjwt.ExpiredSignatureError as exc:
        raise _SubjectTokenError("subject_token expired") from exc
    except pyjwt.InvalidTokenError as exc:
        raise _SubjectTokenError(f"subject_token invalid: {exc}") from exc

    if not isinstance(claims, dict) or not isinstance(claims.get("sub"), str):
        raise _SubjectTokenError("subject_token claims malformed")
    # Reject service-account subject_tokens — token-exchange is for
    # propagating *user* identity. A service can use client_credentials
    # directly; layering svc-on-svc here just expands the trust radius.
    azp = claims.get("azp")
    if isinstance(azp, str) and azp.startswith("svc-"):
        raise _SubjectTokenError(
            "subject_token must represent a user; got service-account token"
        )
    return claims


def _find_jwk(key_ring: Any, kid: str) -> dict[str, Any] | None:
    """Return the JWK dict for ``kid`` in the active JWK Set, or None."""
    jwks = key_ring.public_jwks()
    for jwk in jwks.get("keys", []):
        if jwk.get("kid") == kid:
            return jwk
    return None


# Defensive helper used in tests to surface unparsed iss claims.
def _issuer_host(token_iss: str) -> str | None:
    try:
        return urlparse(token_iss).hostname
    except (ValueError, TypeError):
        return None


# ── Long-lived delegation grants (WS3-delegated-user-async) ──────────────


def _delegation_store(request: Request) -> DelegationGrantStore:
    store = getattr(request.app.state, "delegation_grant_store", None)
    if store is None:
        raise RuntimeError(
            "delegation-grant endpoints hit before "
            "app.state.delegation_grant_store was initialised — check "
            "lifecycle.py wiring"
        )
    return store


@router.post("/auth/delegation-grant", include_in_schema=False)
async def auth_delegation_grant(
    request: Request,
    client_id: str = Form(...),
    client_secret: str | None = Form(default=None),
    audience: str = Form(...),
    subject_token: str = Form(...),
    ttl_seconds: int = Form(default=DEFAULT_GRANT_TTL_SECONDS),
) -> JSONResponse:
    """Issue a delegation grant from a still-valid user subject_token.

    Worker startup calls this with the user's bearer + the calling
    service's S2S credential. The grant id is opaque; the worker
    persists it with the run state.
    """
    verifier, registry = _state(request)

    try:
        verified = await verifier.verify(
            client_id=client_id,
            client_secret=client_secret,
            request=request,
        )
    except ClientAuthError as exc:
        status = 403 if exc.error_code == "unauthorized_client" else 401
        return _error(status, exc.error_code, str(exc))

    entry = registry.lookup(verified.client_id)
    if entry is None:
        return _error(401, "invalid_client", "client not registered")
    if not entry.may_act_for(audience):
        return _error(
            403,
            "unauthorized_client",
            f"client {verified.client_id!r} not authorized to act for audience {audience!r}",
        )

    cfg = get_settings()
    try:
        subject_claims = _verify_gatekeeper_token(
            subject_token,
            request=request,
            issuer=cfg.gatekeeper_issuer,
            audience=cfg.internal_token_audience,
        )
    except _SubjectTokenError as exc:
        return _error(400, "invalid_grant", str(exc))

    # Strip claims that are mint-time / per-token rather than identity:
    # iat, exp, nbf, jti, aud, iss, scope. Keep the user-identity ones
    # so the redeem path can rebuild a fresh internal JWT later.
    identity: dict[str, Any] = {
        k: v
        for k, v in subject_claims.items()
        if k
        in (
            "sub",
            TENANT_ID_CLAIM,
            TENANT_SLUG_CLAIM,
            EMAIL_CLAIM,
            "email",
            "realm_access",
        )
    }

    store = _delegation_store(request)
    try:
        grant_id, expires_at = await store.issue(
            identity=identity,
            ttl_seconds=ttl_seconds,
        )
    except DelegationGrantError as exc:
        return _error(400, "invalid_request", str(exc))

    logger.info(
        "delegation_grant_issued client_id=%s sub=%s aud=%s ttl=%ds",
        verified.client_id,
        identity.get("sub"),
        audience,
        ttl_seconds,
    )
    return JSONResponse(
        content={
            "grant_id": grant_id,
            "expires_at": expires_at,
        }
    )


@router.post("/auth/delegation-exchange", include_in_schema=False)
async def auth_delegation_exchange(
    request: Request,
    client_id: str = Form(...),
    client_secret: str | None = Form(default=None),
    audience: str = Form(...),
    grant_id: str = Form(...),
    scope: str | None = Form(default=None),
) -> JSONResponse:
    """Redeem a delegation grant for a freshly-minted user-delegated JWT.

    Worker step handlers call this each time they need to act on the
    user's behalf. The grant can be redeemed many times until natural
    TTL expiry, so a multi-step run pays one issue + N redeems.
    """
    verifier, registry = _state(request)

    try:
        verified = await verifier.verify(
            client_id=client_id,
            client_secret=client_secret,
            request=request,
        )
    except ClientAuthError as exc:
        status = 403 if exc.error_code == "unauthorized_client" else 401
        return _error(status, exc.error_code, str(exc))

    entry = registry.lookup(verified.client_id)
    if entry is None:
        return _error(401, "invalid_client", "client not registered")
    if audience not in entry.audiences:
        return _error(
            403,
            "unauthorized_client",
            f"client {verified.client_id!r} not allowed for audience {audience!r}",
        )
    if not entry.may_act_for(audience):
        return _error(
            403,
            "unauthorized_client",
            f"client {verified.client_id!r} not authorized to act for audience {audience!r}",
        )

    store = _delegation_store(request)
    try:
        identity = await store.redeem(grant_id)
    except DelegationGrantError as exc:
        return _error(400, "invalid_grant", str(exc))

    user_scopes = (
        frozenset(split_scope_string(identity.get("scope", "")))
        if identity.get("scope")
        else frozenset()
    )
    allowed = entry.allowed_scopes_for(audience)
    requested = split_scope_string(scope) if scope else None
    candidate = scopes_intersection(allowed, requested)
    # If the original subject_token had scopes recorded, preserve the
    # privilege-escalation safeguard (registry ∩ user ∩ requested);
    # otherwise allow registry ∩ requested (the original consent
    # implicitly authorised the registry's allowed set).
    effective = (
        scopes_intersection(candidate, user_scopes) if user_scopes else candidate
    )
    if not effective:
        return _error(400, "invalid_scope", "no scopes survive intersection")

    cfg = get_settings()
    payload = _delegated_user_payload(
        subject_claims=identity,
        actor_client_id=entry.client_id,
        scopes=effective,
        target_service=audience,
    )
    token, exp = mint_internal_token(
        keycloak_payload=payload,
        key_ring=request.app.state.key_ring,
        issuer=cfg.gatekeeper_issuer,
        audience=cfg.internal_token_audience,
        ttl_seconds=cfg.internal_token_ttl_seconds,
        auth_method="cookie",
    )
    expires_in = max(0, exp - int(time.time()))
    logger.info(
        "delegation_grant_exchanged client_id=%s grant=%s sub=%s target=%s scopes=%d",
        verified.client_id,
        grant_id,
        identity.get("sub"),
        audience,
        len(effective),
    )
    return _success(
        access_token=token,
        expires_in=expires_in,
        scope=" ".join(sorted(effective)),
    )


@router.delete("/auth/delegation-grant/{grant_id}", include_in_schema=False)
async def auth_delegation_revoke(
    request: Request,
    grant_id: str,
) -> JSONResponse:
    """Operator-triggered grant revocation.

    Authentication: requires the same client_credentials as issuance —
    we accept them as form fields (DELETE bodies are unusual but
    httpx supports them). Returns 204 on success, 404 when the grant
    is already gone.
    """
    # DELETE doesn't carry form by default; pull from body if present.
    form = await request.form()
    client_id = form.get("client_id")
    client_secret = form.get("client_secret")
    if not client_id:
        return _error(400, "invalid_request", "client_id required")

    verifier, registry = _state(request)
    try:
        verified = await verifier.verify(
            client_id=str(client_id),
            client_secret=str(client_secret) if client_secret else None,
            request=request,
        )
    except ClientAuthError as exc:
        status = 403 if exc.error_code == "unauthorized_client" else 401
        return _error(status, exc.error_code, str(exc))

    entry = registry.lookup(verified.client_id)
    if entry is None:
        return _error(401, "invalid_client", "client not registered")

    store = _delegation_store(request)
    deleted = await store.revoke(grant_id)
    return JSONResponse(
        status_code=204 if deleted else 404,
        content={} if deleted else {"error": "not_found"},
    )


__all__ = [
    "GRANT_CLIENT_CREDENTIALS",
    "GRANT_TOKEN_EXCHANGE",
    "TOKEN_TYPE_ACCESS_TOKEN",
    "router",
]
