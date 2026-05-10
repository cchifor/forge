"""``auth.*`` features — identity, RBAC, and S2S authentication primitives.

Ports the platform-auth model (Gatekeeper as sole token authority, ES256
algorithm pinning, BFF Redis sessions with two-key TTL, scope-based
authorization, RFC 8693 token-exchange) into forge-generated projects.

This namespace ships:

- ``platform-auth`` Python SDK (Phase 1) — ``AuthGuard``, ``IdentityContext``,
  ``JWKSCache``, ``S2SClient``, ``MayActPolicy``, scope matching, test-token
  minter. Lands in the generated project at ``sdks/platform-auth/``.
- (Phase 2+) Token-authority Gatekeeper, two-key Redis sessions, ``/auth/jwks``,
  ``/auth/token``, ``/auth/session`` GET+POST, gatekeeper-keygen init service.
- (Phase 4) ``@forge/platform-auth-node`` SDK with feature parity.
- (Phase 6) ``platform-auth-rs`` SDK with feature parity.
- (Phase 8) Frontend ``useSessionTimeout`` composable and ``SessionTimeoutModal``.

Cross-reference: the design rationale and rollout plan live in
``~/.claude/plans/review-the-c-users-chifo-work-platform-a-pure-torvalds.md``.
"""

from __future__ import annotations

from forge.features.auth import (  # noqa: F401, E402
    fragments,
    options,
)
