"""Construct an :class:`platform_auth.AuthGuard` from this service's config.

Phase 4 single-mode wiring. The migration-window's three-mode logic
(Keycloak-only / dual-issuer / gatekeeper-only) collapses to one path:
every backend trusts gatekeeper as the sole token authority. Per-tenant
``trust_map`` enforcement is active; algorithms are locked to ES256.
"""

from __future__ import annotations

from dataclasses import dataclass

from platform_auth import (
    AuthGuard,
    InMemoryIssuerTrustMap,
    JWKSCache,
    MayActPolicy,
    StaticMayActPolicy,
)

from forge_core.domain.config import AuthConfig


def issuer_url(config: AuthConfig) -> str:
    """Trusted issuer URL — gatekeeper's base URL."""
    return str(config.server_url).rstrip("/")


def jwks_uri(config: AuthConfig) -> str:
    """JWKS URI for the trusted issuer.

    Defaults to ``<server_url>/auth/jwks`` per gatekeeper's Phase 0
    contract; ``config.jwks_uri`` overrides for off-spec deployments.
    """
    if config.jwks_uri is not None:
        return str(config.jwks_uri).rstrip("/")
    return f"{issuer_url(config)}/auth/jwks"


@dataclass(slots=True)
class AuthGuardBundle:
    """The auth machinery + the collaborators that the lifecycle owns."""

    guard: AuthGuard
    jwks: JWKSCache
    trust_map: InMemoryIssuerTrustMap
    # The may-act policy collaborator. Typed as the ``MayActPolicy`` protocol
    # so the bundle accepts any implementation — the gatekeeper path supplies
    # a ``StaticMayActPolicy`` (the default below), while the in-memory dev
    # issuer supplies ``AllowAllMayActPolicy`` (break-glass; dev/test only).
    may_act: MayActPolicy


def build_auth_guard(
    config: AuthConfig,
    *,
    trust_map: InMemoryIssuerTrustMap | None = None,
    may_act: MayActPolicy | None = None,
) -> AuthGuardBundle:
    """Wire an :class:`AuthGuard` against the configured gatekeeper issuer."""
    jwks = JWKSCache()
    jwks.register_issuer(issuer_url(config), jwks_uri(config))

    trust = trust_map if trust_map is not None else InMemoryIssuerTrustMap()
    policy = may_act if may_act is not None else StaticMayActPolicy()

    guard = AuthGuard(
        audience=config.audience,
        jwks=jwks,
        trust_map=trust,
        may_act=policy,
        algorithms=("ES256",),
    )
    return AuthGuardBundle(
        guard=guard,
        jwks=jwks,
        trust_map=trust,
        may_act=policy,
    )
