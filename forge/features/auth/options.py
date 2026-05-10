"""``auth.*`` options — identity, RBAC, and S2S authentication.

Phase 1 registers the discriminator (``auth.mode``) and the realised SDK
fragment for the Python backend. Subsequent phases extend this module:

- Phase 2 adds Gatekeeper-as-issuer config (algorithms, tenant claim,
  signing-key backend, BFF session toggles).
- Phase 4/6 extend ``auth.mode``'s ``enables`` tuple to include the
  Node and Rust SDK fragments respectively.
- Phase 8 adds frontend session-timeout knobs (idle / absolute defaults,
  warn-at threshold, rate limit).
"""

from __future__ import annotations

from forge.options._registry import (
    FeatureCategory,
    Option,
    OptionType,
    register_option,
)

register_option(
    Option(
        path="auth.mode",
        type=OptionType.ENUM,
        default="generate",
        options=("generate", "none"),
        summary="Whether forge scaffolds the platform-auth stack for this project.",
        description="""\
Layer discriminator for the authentication subsystem. ``generate`` ships
the platform-auth model end-to-end:

- Per-language verifier SDKs at ``<project>/sdks/platform-auth*/``
  (Python / Node / Rust). Each ships ``AuthGuard``, ``IdentityContext``,
  multi-issuer ``JWKSCache`` with stale-serve, ``MayActPolicy`` (RFC 8693),
  ``IssuerTrustMap``, ``RevocationStore``, scope-matching with wildcards,
  test-token minter. Cross-language correctness gated by the shared
  17-scenario parity spec at ``forge/tests/contract/auth_sdk_parity/``.
- Per-language service-template middleware that wires the SDK into
  FastAPI / Fastify / Axum: single-pass verification, request-state
  binding, RFC 7807 problem-response error mapping, identical
  ``/health`` / ``/metrics`` / ``/docs`` skip-list across all three
  backends.
- Per-frontend session-timeout composables (Vue / Svelte / Flutter)
  implementing the BFF + inactivity-timeout SPA pattern: drift-immune
  countdown, BroadcastChannel cross-tab leader election (web),
  visibility gating, debounced 30s ``POST /auth/session`` on real
  user-interaction events.

The Gatekeeper container (token-authority + BFF session manager) is
separately gated until the Phase 2 cutover removes the legacy
``forge/templates/infra/gatekeeper/`` template — see the deferred
``platform_auth_gatekeeper`` + ``platform_auth_gatekeeper_keygen``
fragments. ``forge --migrate auth-keycloak-to-platform-auth`` carries
existing 1.1.x projects across the cutover.

``none`` skips the auth stack entirely — useful for stateless
internal-only services running behind a trusted boundary.

BACKENDS: python + node + rust (SDKs + middleware are tier-1).
ENDPOINTS: none directly — the SDKs are libraries; service templates
wire them into request middleware.
REQUIRES: Keycloak realm (existing) for the human-login flow;
Gatekeeper container (Phase 2 cutover) to mint internal JWTs.""",
        category=FeatureCategory.PLATFORM,
        enables={
            "generate": (
                # SDK ports — one per backend language. Ship to
                # ``<project>/sdks/platform-auth*/`` (a NEW path, no
                # collision with forge's existing service templates).
                "platform_auth_sdk_python",
                "platform_auth_sdk_node",
                "platform_auth_sdk_rust",
                # Per-frontend SPA session-timeout — ships composable
                # + modal at conventional Vue / Svelte / Flutter paths
                # using NEW filenames (``useSessionTimeout`` /
                # ``session-timeout.svelte.ts`` /
                # ``session_timeout_service.dart``) — no collision
                # with the existing per-frontend auth files.
                "platform_auth_session_timeout_vue",
                "platform_auth_session_timeout_svelte",
                "platform_auth_session_timeout_flutter",
                # Phase 3 Wave 2 (cut over) — Python service-template
                # middleware. Legacy ``service/security/providers/``,
                # ``service/security/{auth,base}.py``,
                # ``service/client/auth.py`` were removed from the
                # python-service-template; the fragment ships their
                # platform-auth replacements at the same paths.
                # ``app/core/lifecycle.py``'s auth setup block was
                # rewritten to use ``build_auth_guard`` +
                # ``initialize_auth(bundle=...)``.
                "platform_auth_python_middleware",
                # Phase 5 Wave 2 (cut over) — Node service-template
                # middleware. Legacy ``middleware/tenant.ts``,
                # ``lib/http-client.ts`` removed; Repository/Service/
                # route layers refactored from ``TenantContext``
                # (userId / customerId / email / roles) to
                # ``IdentityContext`` (tenantId / subject / scopes /
                # roles). The fragment's ``bootstrapAuth(app)`` is
                # injected at the FORGE markers in ``app.ts``.
                "platform_auth_node_middleware",
                # Phase 7 Wave 2 (cut over) — Rust service-template
                # middleware. Legacy ``middleware/tenant.rs`` (header-
                # trust ``FromRequestParts``) and ``client.rs`` (S2S
                # header propagation) removed; Repository / service /
                # route layers refactored to take ``&IdentityContext``
                # from ``platform_auth``. ``main.rs`` calls
                # ``init_auth()`` (injected at FORGE:STARTUP_INIT) and
                # ``app.rs`` adds the ``axum::middleware::from_fn``
                # auth_middleware layer.
                "platform_auth_rust_middleware",
                # Phase 2 Wave 2 (cut over) — Gatekeeper as token
                # authority + signing-key init service. Imperative
                # gatekeeper compose block in
                # ``forge/templates/deploy/docker-compose.yml.j2`` and
                # the legacy ``forge/templates/infra/gatekeeper/``
                # tree were removed. Declarative ``compose.yaml``
                # entries on these two fragments register the
                # gatekeeper + gatekeeper-keygen sidecars via
                # ``forge.services.fragment_compose``.
                "platform_auth_gatekeeper",
                "platform_auth_gatekeeper_keygen",
                # ``platform_auth_gatekeeper`` and
                # ``platform_auth_gatekeeper_keygen`` are also held
                # back pending the imperative compose-block removal
                # in ``forge/templates/deploy/docker-compose.yml.j2``
                # and the legacy ``forge/templates/infra/gatekeeper/``
                # template removal — Phase 2 Wave 2.
            ),
        },
    )
)
