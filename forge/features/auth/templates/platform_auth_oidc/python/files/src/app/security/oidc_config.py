"""Environment-driven configuration for the generic OIDC auth provider.

``auth.provider=oidc_generic`` points the service's issuer-agnostic
``AuthGuard`` at *any* external OIDC issuer — Keycloak (direct, no
Gatekeeper), Auth0, AWS Cognito, Okta, Azure AD, … — by reading a small set
of ``AUTH_PROVIDER_*`` environment variables:

==============================  ===================================  =========
Env var                         Meaning                              Default
==============================  ===================================  =========
``AUTH_PROVIDER_ISSUER``        Issuer base URL (the ``iss`` claim    *(req.)*
                                value AND the OIDC discovery root).
``AUTH_PROVIDER_AUDIENCE``      Expected ``aud`` claim.               *(req.)*
``AUTH_PROVIDER_JWKS_URI``      Explicit JWKS URI; skips discovery.   *(none)*
``AUTH_PROVIDER_ALGORITHMS``    CSV of accepted signing algs.         ``RS256``
``AUTH_PROVIDER_TENANT_CLAIM``  Dot-path to the tenant id in the      ``tenant_id``
                                verified claims.
==============================  ===================================  =========

This module is intentionally **dependency-light**: it imports nothing from
FastAPI, the service framework, or the platform-auth SDK, so it can be unit
tested in isolation and reused by tooling. The only collaborators are the
stdlib and the verified-claims dicts handed to :class:`ClaimMapper`.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

_log = logging.getLogger(__name__)

# Algorithms this provider is willing to verify. Asymmetric algs are the
# common OIDC case (the IdP signs with a private key, we hold only the public
# JWKS); ``HS256`` is supported for the symmetric-secret deployments some
# IdPs still offer, but the operator must point ``AUTH_PROVIDER_JWKS_URI`` /
# the shared secret accordingly. ``none`` is never accepted.
#
# !! SECURITY — HS256 is the classic JWT *algorithm-confusion* footgun. HS256
# is a symmetric MAC keyed on a *shared secret*; RS256/ES256 are asymmetric and
# verify against the IdP's *public* JWKS. If you accept HS256 *while* feeding
# this provider a JWKS endpoint, an attacker can forge a token by HMAC-signing
# it with the public key (which is public) as the HS256 secret, and it will
# verify. ONLY enable HS256 when the issuer signs with a symmetric shared
# secret that this service holds privately — NEVER alongside a JWKS endpoint.
# ``parse_algorithms`` logs a loud warning whenever HS256 is configured.
SUPPORTED_ALGORITHMS: frozenset[str] = frozenset({"RS256", "ES256", "HS256"})

DEFAULT_ALGORITHMS: tuple[str, ...] = ("RS256",)
DEFAULT_TENANT_CLAIM = "tenant_id"


class OIDCConfigError(ValueError):
    """Raised when the ``AUTH_PROVIDER_*`` environment is invalid."""


def parse_algorithms(raw: str | None) -> tuple[str, ...]:
    """Parse the ``AUTH_PROVIDER_ALGORITHMS`` CSV into a validated tuple.

    Empty / unset → :data:`DEFAULT_ALGORITHMS` (``RS256``). Each entry is
    upper-cased and checked against :data:`SUPPORTED_ALGORITHMS`; ``none``
    (in any case) is rejected outright, and an unknown algorithm raises so a
    typo surfaces at boot rather than as a silent verify failure.

    If ``HS256`` is among the configured algorithms a loud ``logging.warning``
    is emitted: HS256 is a symmetric MAC and is the classic JWT
    algorithm-confusion footgun — it is safe only with a privately-held shared
    secret and must never be combined with a JWKS endpoint.
    """
    if raw is None or not raw.strip():
        return DEFAULT_ALGORITHMS
    algs: list[str] = []
    for chunk in raw.split(","):
        alg = chunk.strip().upper()
        if not alg:
            continue
        if alg == "NONE":
            raise OIDCConfigError("algorithm 'none' is forbidden")
        if alg not in SUPPORTED_ALGORITHMS:
            supported = ", ".join(sorted(SUPPORTED_ALGORITHMS))
            raise OIDCConfigError(f"unsupported algorithm {alg!r}; supported: {supported}")
        if alg not in algs:
            algs.append(alg)
    if not algs:
        return DEFAULT_ALGORITHMS
    if "HS256" in algs:
        # Alg-confusion footgun: HS256 (symmetric MAC) must only be used with a
        # private shared secret, NEVER with a JWKS endpoint (the public key
        # would double as the HMAC secret, letting anyone forge tokens).
        _log.warning(
            "HS256 is enabled in AUTH_PROVIDER_ALGORITHMS. HS256 is a symmetric "
            "algorithm and is safe ONLY with a privately-held shared secret; "
            "never combine it with a JWKS endpoint (AUTH_PROVIDER_JWKS_URI) or "
            "discovery, which exposes you to a JWT algorithm-confusion attack."
        )
    return tuple(algs)


@dataclass(slots=True, frozen=True)
class OIDCSettings:
    """Resolved, validated configuration for the OIDC provider."""

    issuer: str
    audience: str
    algorithms: tuple[str, ...] = DEFAULT_ALGORITHMS
    jwks_uri: str | None = None
    tenant_claim: str = DEFAULT_TENANT_CLAIM

    def __post_init__(self) -> None:
        if not self.issuer:
            raise OIDCConfigError("AUTH_PROVIDER_ISSUER is required for auth.provider=oidc_generic")
        if not self.audience:
            raise OIDCConfigError(
                "AUTH_PROVIDER_AUDIENCE is required for auth.provider=oidc_generic"
            )
        if not self.algorithms:
            raise OIDCConfigError("algorithms must be non-empty")
        if not self.tenant_claim:
            raise OIDCConfigError("tenant_claim must be non-empty")

    @property
    def issuer_normalised(self) -> str:
        """Issuer with any trailing slash stripped (discovery + compare)."""
        return self.issuer.rstrip("/")


def load_oidc_settings(
    env: Mapping[str, str] | None = None,
    *,
    fallback_audience: str | None = None,
    fallback_tenant_claim: str | None = None,
) -> OIDCSettings:
    """Build :class:`OIDCSettings` from ``env`` (defaults to ``os.environ``).

    ``fallback_audience`` / ``fallback_tenant_claim`` let the installer pass
    the service's already-configured ``AuthConfig`` values as defaults when
    the dedicated ``AUTH_PROVIDER_*`` vars are unset — so a deployment that
    already configures ``audience`` / ``tenant_id_claim`` does not have to
    duplicate them.
    """
    source = os.environ if env is None else env

    issuer = (source.get("AUTH_PROVIDER_ISSUER") or "").strip()
    audience = (source.get("AUTH_PROVIDER_AUDIENCE") or fallback_audience or "").strip()
    jwks_raw = (source.get("AUTH_PROVIDER_JWKS_URI") or "").strip()
    algorithms = parse_algorithms(source.get("AUTH_PROVIDER_ALGORITHMS"))
    tenant_claim = (
        source.get("AUTH_PROVIDER_TENANT_CLAIM") or fallback_tenant_claim or DEFAULT_TENANT_CLAIM
    ).strip()

    return OIDCSettings(
        issuer=issuer,
        audience=audience,
        algorithms=algorithms,
        jwks_uri=jwks_raw or None,
        tenant_claim=tenant_claim,
    )


_UNSET = object()


class ClaimMapper:
    """Extract identity fields from an IdP's verified claims.

    Different IdPs name the tenant claim differently (``tenant_id``,
    ``org_id``, ``https://example.com/tenant``, ``custom:tenant`` for
    Cognito, a nested ``organization.id`` for some Auth0 setups, …).
    :class:`ClaimMapper` resolves the tenant id via a configurable *dot-path*
    so the same verifier wiring works against every provider.

    A dot-path traverses nested mappings: ``"organization.id"`` reads
    ``claims["organization"]["id"]``. A literal dotted claim key (the common
    case for namespaced OIDC claims like ``https://platform/tenant_id``) is
    matched first as a whole key before falling back to dotted traversal, so
    URL-shaped claim names work without escaping.

    Kept deliberately tiny + SDK-free: it operates on plain mappings only.
    """

    def __init__(self, tenant_claim: str = DEFAULT_TENANT_CLAIM) -> None:
        if not tenant_claim:
            raise OIDCConfigError("tenant_claim must be non-empty")
        self._tenant_claim = tenant_claim

    @property
    def tenant_claim(self) -> str:
        return self._tenant_claim

    def extract(self, claims: Mapping[str, Any], path: str | None = None) -> Any:
        """Return the value at ``path`` (default: the tenant claim) or ``None``.

        Resolution order:

        1. Whole-key match — handles literal dotted / URL-shaped claim names.
        2. Dotted traversal — splits on ``.`` and walks nested mappings.

        Returns ``None`` when the path resolves to nothing (a missing claim
        is a verifier decision, not a mapper error).
        """
        dotted = self._tenant_claim if path is None else path
        # 1. Literal whole-key hit (namespaced URL claims, ``custom:tenant``).
        if dotted in claims:
            return claims[dotted]
        # 2. Nested traversal.
        current: Any = claims
        for segment in dotted.split("."):
            if not isinstance(current, Mapping):
                return None
            nxt = current.get(segment, _UNSET)
            if nxt is _UNSET:
                return None
            current = nxt
        return current

    def tenant_id(self, claims: Mapping[str, Any]) -> Any:
        """Convenience wrapper: extract the configured tenant claim."""
        return self.extract(claims)


__all__ = [
    "DEFAULT_ALGORITHMS",
    "DEFAULT_TENANT_CLAIM",
    "SUPPORTED_ALGORITHMS",
    "ClaimMapper",
    "OIDCConfigError",
    "OIDCSettings",
    "load_oidc_settings",
    "parse_algorithms",
]
