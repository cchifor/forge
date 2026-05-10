# src/app/gatekeeper/internal_token.py
"""Mint gatekeeper-internal JWTs for downstream backends.

Gatekeeper translates a verified Keycloak access token into a fresh JWT
signed by gatekeeper. Backends verify against gatekeeper's JWKS instead
of Keycloak's, removing the per-service issuer/realm/audience config
surface that drove the recurring SPA refresh-loop class.

Claim set:

* Standard: ``iss``, ``aud``, ``sub``, ``iat``, ``nbf=iat-5``, ``exp``,
  ``jti=uuid4()``.
* ``exp`` is clamped to ``min(keycloak_exp, iat + ttl_seconds)`` so the
  internal token can never outlive its parent Keycloak access token —
  revocation latency = Keycloak access-token TTL + at most one TTL.
* Audit/forensics: ``keycloak_jti`` and ``keycloak_iss`` link every
  internal token back to the Keycloak session that produced it.
* Identity: ``https://platform/tenant_id``, ``https://platform/tenant_slug``,
  ``https://platform/email``, ``roles`` (Keycloak default roles filtered),
  ``scope``, ``auth_method`` (``cookie`` for human / ``api_key`` for machine).
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Literal

from app.gatekeeper.helpers import JWTPayload
from app.gatekeeper.key_store import KeyRing

logger = logging.getLogger(__name__)

NBF_SKEW_SECONDS = 5

TENANT_ID_CLAIM = "https://platform/tenant_id"
TENANT_SLUG_CLAIM = "https://platform/tenant_slug"
EMAIL_CLAIM = "https://platform/email"

# Keycloak emits a few realm-default roles that aren't useful to backends.
# Strip them so authorization checks operate on meaningful role names.
_FILTERED_ROLES: frozenset[str] = frozenset(
    {
        "offline_access",
        "uma_authorization",
    }
)
# Match-prefix filter for realm-specific defaults like ``default-roles-app``.
_FILTERED_ROLE_PREFIXES: tuple[str, ...] = ("default-roles-",)


AuthMethod = Literal["cookie", "api_key"]


def _filter_roles(raw: list[str]) -> list[str]:
    return [
        role
        for role in raw
        if role not in _FILTERED_ROLES
        and not any(role.startswith(p) for p in _FILTERED_ROLE_PREFIXES)
    ]


def mint_internal_token(
    *,
    keycloak_payload: JWTPayload | dict[str, Any],
    key_ring: KeyRing,
    issuer: str,
    audience: str,
    ttl_seconds: int,
    auth_method: AuthMethod = "cookie",
    now: int | None = None,
) -> tuple[str, int]:
    """Mint an ES256 JWT signed by *key_ring*'s active key.

    Returns ``(token, exp_unix)``. The exp is min(keycloak_exp, iat+ttl).

    Parameters
    ----------
    keycloak_payload:
        The verified Keycloak access-token payload (output of
        ``app.gatekeeper.jwks.verify_token``). Must carry ``sub``; other
        claims are copied opportunistically.
    key_ring:
        The signing keys. Only the ``active`` entry is used.
    issuer, audience:
        ``iss`` and ``aud`` claims for the minted token. These are
        gatekeeper-controlled so backends can pin them to a single value.
    ttl_seconds:
        Maximum lifetime; clamped against the Keycloak token's own ``exp``.
    auth_method:
        ``cookie`` for human / SPA traffic, ``api_key`` for machine. Lets
        backends apply different policies without re-routing per track.
    now:
        Override for tests. Production callers always pass ``None``.
    """
    now = now if now is not None else int(time.time())

    # Clamp exp so the internal token never outlives the Keycloak token.
    # Falls back to ``now + ttl`` when keycloak_payload has no exp (only
    # happens in synthetic test inputs; real Keycloak tokens always carry it).
    keycloak_exp = int(keycloak_payload.get("exp", now + ttl_seconds))
    exp = min(keycloak_exp, now + ttl_seconds)

    realm_access = keycloak_payload.get("realm_access") or {}
    raw_roles: list[str] = []
    if isinstance(realm_access, dict):
        roles_field = realm_access.get("roles", [])
        if isinstance(roles_field, list):
            raw_roles = [str(r) for r in roles_field]
    roles = _filter_roles(raw_roles)

    claims: dict[str, Any] = {
        "iss": issuer,
        "aud": audience,
        "sub": str(keycloak_payload["sub"]),
        "iat": now,
        "nbf": now - NBF_SKEW_SECONDS,
        "exp": exp,
        "jti": str(uuid.uuid4()),
        "auth_method": auth_method,
        "roles": roles,
    }

    # Audit-link claims: surface the originating Keycloak token in every
    # backend log line so SOC investigations can trace from a backend
    # request all the way back to the IdP session.
    if kc_jti := keycloak_payload.get("jti"):
        claims["keycloak_jti"] = str(kc_jti)
    if kc_iss := keycloak_payload.get("iss"):
        claims["keycloak_iss"] = str(kc_iss)

    # Identity claims: pass through when present. Missing tenant_id is
    # not a mint-time error — gatekeeper's tenant-assignment flow runs
    # earlier and would have rejected the request before reaching us.
    if tenant_id := keycloak_payload.get(TENANT_ID_CLAIM):
        claims[TENANT_ID_CLAIM] = tenant_id
    if tenant_slug := keycloak_payload.get(TENANT_SLUG_CLAIM):
        claims[TENANT_SLUG_CLAIM] = tenant_slug
    if email := keycloak_payload.get("email") or keycloak_payload.get(EMAIL_CLAIM):
        claims[EMAIL_CLAIM] = email
    if scope := keycloak_payload.get("scope"):
        claims["scope"] = scope

    # OAuth2 / RFC 8693 actor claims used by /auth/token. Always optional —
    # the UI mint path doesn't set them, so user tokens never carry these.
    # Service-account tokens (from /auth/token client_credentials) carry
    # ``azp``; token-exchange mints additionally carry ``act``.
    if azp := keycloak_payload.get("azp"):
        claims["azp"] = azp
    if act := keycloak_payload.get("act"):
        claims["act"] = act
    # Records the intended downstream service for service-token mints.
    # JWT ``aud`` is the platform-wide constant; this claim is for audit
    # and per-service authorization decisions.
    if target := keycloak_payload.get("platform_target_service"):
        claims["platform_target_service"] = target

    token, kid = key_ring.sign(claims)
    logger.debug(
        "minted_internal_token",
        extra={
            "kid": kid,
            "sub": claims["sub"],
            "exp": exp,
            "ttl": exp - now,
            "auth_method": auth_method,
        },
    )
    return token, exp
