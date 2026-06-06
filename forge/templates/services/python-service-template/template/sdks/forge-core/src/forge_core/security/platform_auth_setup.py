"""Construct an :class:`forge_core.security.AuthGuard` from the service config.

Builds the always-shipped, weld-free auth bundle the base lifecycle wires onto
the app. It reads the generic OIDC :class:`forge_core.domain.AuthConfig`
(issuer / realm / client / audience / claim names) and stands up an
:class:`AuthGuard` over a :class:`JWKSCache` registered for the configured
issuer.

``build_auth_guard`` is a *module-level symbol*: optional auth providers
shipped at ``auth.mode=generate`` (the in-memory dev issuer, the external-OIDC
provider) rebind ``app.core.lifecycle.build_auth_guard`` at
``FORGE:APP_POST_CONFIGURE`` to swap in their own issuer wiring while the rest
of the auth stack stays byte-identical. The default algorithm is ES256; an
issuer that mints RS256 tokens overrides ``algorithms`` (the providers do).
"""

from __future__ import annotations

from dataclasses import dataclass

from forge_core.domain.config import AuthConfig
from forge_core.security.guard import AuthGuard
from forge_core.security.jwks import JWKSCache
from forge_core.security.trust import InMemoryIssuerTrustMap


def issuer_url(config: AuthConfig) -> str:
    """Trusted issuer URL — the configured server's base URL."""
    return str(config.server_url).rstrip("/")


def jwks_uri(config: AuthConfig) -> str:
    """JWKS URI for the trusted issuer.

    Honours an explicit ``config.jwks_uri`` override; otherwise derives the
    conventional ``<server_url>/realms/<realm>/protocol/openid-connect/certs``
    endpoint.
    """
    return config.default_jwks_uri


@dataclass(slots=True)
class AuthGuardBundle:
    """The auth machinery + the collaborators that the lifecycle owns."""

    guard: AuthGuard
    jwks: JWKSCache
    trust_map: InMemoryIssuerTrustMap


def build_auth_guard(
    config: AuthConfig,
    *,
    trust_map: InMemoryIssuerTrustMap | None = None,
) -> AuthGuardBundle:
    """Wire an :class:`AuthGuard` against the configured issuer."""
    jwks = JWKSCache()
    jwks.register_issuer(issuer_url(config), jwks_uri(config))

    trust = trust_map if trust_map is not None else InMemoryIssuerTrustMap()

    guard = AuthGuard(
        audience=config.audience,
        jwks=jwks,
        trust_map=trust,
        tenant_id_claim=config.tenant_id_claim,
        tenant_slug_claim=config.tenant_slug_claim,
    )
    return AuthGuardBundle(guard=guard, jwks=jwks, trust_map=trust)


__all__ = [
    "AuthGuardBundle",
    "build_auth_guard",
    "issuer_url",
    "jwks_uri",
]
