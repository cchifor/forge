"""Wire a generic external OIDC issuer into the application's auth guard.

The ``oidc_generic`` provider ships this installer in place of the Gatekeeper
sidecar. It points the issuer-agnostic platform-auth ``AuthGuard`` at *any*
external OIDC issuer (Keycloak direct, Auth0, Cognito, Okta, …) by:

1. reading the ``AUTH_PROVIDER_*`` env config (:mod:`app.security.oidc_config`),
2. resolving the issuer's JWKS URI via OIDC discovery — unless an explicit
   ``AUTH_PROVIDER_JWKS_URI`` override is given (:mod:`app.security.oidc_discovery`),
3. constructing an :class:`AuthGuard` over a ``JWKSCache`` registered for that
   issuer + JWKS URI, with the configured algorithms + audience + tenant claim.

:func:`install_oidc_auth` is injected into the application factory at
``FORGE:APP_POST_CONFIGURE`` — i.e. *before* ``AppLifecycle.bootstrap`` runs —
so it rebinds the ``build_auth_guard`` symbol that ``app.core.lifecycle``
imported at module load. This is the exact same narrow-rebinding seam the
``in_memory`` provider uses; the SDK + middleware stay byte-identical and only
the *issuer* the guard trusts changes.

No Gatekeeper container, no Keycloak realm provisioning, no Redis — the issuer
is external and env-driven.
"""

from __future__ import annotations

import asyncio
import logging
from uuid import UUID

import app.core.lifecycle as _lifecycle
import httpx
from app.core.config import Settings
from app.security.oidc_config import ClaimMapper, OIDCSettings, load_oidc_settings
from app.security.oidc_discovery import OIDCDiscovery
from fastapi import FastAPI
from platform_auth import (
    AuthGuard,
    InMemoryIssuerTrustMap,
    JWKSCache,
    StaticMayActPolicy,
    TenantTrust,
)
from forge_core.domain.config import AuthConfig
from service.security.platform_auth_setup import AuthGuardBundle

logger = logging.getLogger(__name__)

# ``app.state`` keys for the resolved OIDC settings + the claim mapper, so
# downstream code (diagnostics, custom tenant resolution) can reach them.
OIDC_SETTINGS_STATE_KEY = "oidc_settings"
OIDC_CLAIM_MAPPER_STATE_KEY = "oidc_claim_mapper"

# Default/known tenant the configured issuer is seeded for, mirroring the
# ``in_memory`` provider's ``DEV_TENANT_ID``. Seeding the trust map with this
# tenant→issuer binding is what lets the guard run ``strict_trust=True`` and
# still accept tokens for the configured issuer (single-realm deployments).
# Multi-tenant deployments register their real tenants out of band (TMS / a
# populated trust map injected via ``build_oidc_auth_guard(trust_map=...)``).
DEFAULT_TENANT_ID = UUID("11111111-1111-1111-1111-111111111111")


def resolve_jwks_uri(settings: OIDCSettings) -> str:
    """Resolve the JWKS URI for ``settings`` synchronously.

    Honours ``AUTH_PROVIDER_JWKS_URI`` (no network), else runs OIDC discovery
    (``<issuer>/.well-known/openid-configuration``) and falls back to the
    Keycloak ``/protocol/openid-connect/certs`` path if discovery fails.

    Runs the async :class:`OIDCDiscovery` via :func:`asyncio.run` because the
    application factory (where this is called) is synchronous and no event
    loop is running yet.
    """

    async def _run() -> str:
        discovery = OIDCDiscovery()
        try:
            return await discovery.resolve_jwks_uri(
                settings.issuer_normalised, override=settings.jwks_uri
            )
        finally:
            await discovery.aclose()

    return asyncio.run(_run())


def build_oidc_auth_guard(
    config: AuthConfig,
    settings: OIDCSettings,
    *,
    jwks_uri: str | None = None,
    trust_map: InMemoryIssuerTrustMap | None = None,
    may_act: StaticMayActPolicy | None = None,
    http_client: httpx.AsyncClient | None = None,
) -> AuthGuardBundle:
    """The ``oidc_generic`` variant of ``build_auth_guard``.

    Registers the discovered (or overridden) ``issuer`` → ``jwks_uri`` pair in
    a ``JWKSCache`` and constructs an :class:`AuthGuard` with the configured
    algorithms + audience + tenant claim.

    The trust map is **seeded** with the configured issuer bound to
    :data:`DEFAULT_TENANT_ID` (mirroring how the ``in_memory`` provider seeds
    its map), and the guard runs with ``strict_trust=True``. This fails closed:
    a token from an *unknown* issuer / for an *unregistered* tenant is rejected,
    while a token for the configured issuer + known tenant is accepted. Pass an
    explicit ``trust_map`` to register additional tenants out of band (TMS /
    multi-tenant realms) — it is used verbatim, so callers that want a different
    posture supply their own pre-populated map.

    ``jwks_uri`` may be passed pre-resolved (the installer resolves it once);
    when omitted it is resolved here via :func:`resolve_jwks_uri`.
    ``http_client`` is an injection seam for tests (e.g. ``MockTransport``).
    """
    resolved_uri = jwks_uri if jwks_uri is not None else resolve_jwks_uri(settings)

    jwks = JWKSCache(http_client=http_client) if http_client is not None else JWKSCache()
    jwks.register_issuer(settings.issuer_normalised, resolved_uri)

    if trust_map is not None:
        trust = trust_map
    else:
        trust = InMemoryIssuerTrustMap()
        # Seed the configured issuer for the default/known tenant so the guard
        # can fail-closed (strict_trust) while still accepting the configured
        # issuer's tokens.
        trust.set(
            DEFAULT_TENANT_ID,
            TenantTrust(expected_issuer=settings.issuer_normalised, suspended=False),
        )
    policy = may_act if may_act is not None else StaticMayActPolicy()

    guard = AuthGuard(
        audience=settings.audience,
        jwks=jwks,
        trust_map=trust,
        strict_trust=True,
        may_act=policy,
        algorithms=settings.algorithms,
        tenant_id_claim=config.tenant_id_claim,
    )
    return AuthGuardBundle(
        guard=guard,
        jwks=jwks,
        trust_map=trust,
        may_act=policy,
    )


def install_oidc_auth(app: FastAPI, settings: Settings) -> None:
    """Install the external-OIDC issuer and redirect the auth-guard builder.

    Reads the ``AUTH_PROVIDER_*`` env config (falling back to the service's
    already-configured ``audience`` / ``tenant_id_claim`` when the dedicated
    vars are unset), resolves the issuer's JWKS URI once, stashes the resolved
    :class:`OIDCSettings` + :class:`ClaimMapper` on ``app.state``, then rebinds
    ``app.core.lifecycle``'s ``build_auth_guard`` so the guard that lands on
    ``app.state`` verifies tokens from the external issuer.
    """
    auth_config = settings.security.auth
    oidc = load_oidc_settings(
        fallback_audience=auth_config.audience or None,
        fallback_tenant_claim=auth_config.tenant_id_claim or None,
    )

    # Resolve the JWKS URI once (discovery or override), so the per-request
    # guard never blocks on discovery and a discovery outage at boot surfaces
    # immediately rather than on the first authenticated request.
    jwks_uri = resolve_jwks_uri(oidc)

    claim_mapper = ClaimMapper(tenant_claim=oidc.tenant_claim)
    setattr(app.state, OIDC_SETTINGS_STATE_KEY, oidc)
    setattr(app.state, OIDC_CLAIM_MAPPER_STATE_KEY, claim_mapper)

    logger.info(
        "oidc_provider_installed",
        extra={
            "issuer": oidc.issuer_normalised,
            "audience": oidc.audience,
            "algorithms": list(oidc.algorithms),
            "jwks_uri": jwks_uri,
            "tenant_claim": oidc.tenant_claim,
        },
    )

    def _build_oidc(config, **_kwargs):  # type: ignore[no-untyped-def]
        return build_oidc_auth_guard(config, oidc, jwks_uri=jwks_uri)

    _lifecycle.build_auth_guard = _build_oidc


__all__ = [
    "OIDC_CLAIM_MAPPER_STATE_KEY",
    "OIDC_SETTINGS_STATE_KEY",
    "build_oidc_auth_guard",
    "install_oidc_auth",
    "resolve_jwks_uri",
]
