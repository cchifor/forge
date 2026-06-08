"""forge-core security — the always-shipped, weld-free FastAPI auth glue.

This package is the generic, self-contained authentication layer every
generated Python service builds on, at *both* ``auth.mode=generate`` and
``auth.mode=none``. It composes a generic JWT verifier
(:class:`~forge_core.security.AuthGuard` + multi-issuer
:class:`~forge_core.security.JWKSCache` + tenant trust map) with FastAPI's
request lifecycle:

1. The bearer token is extracted via :data:`oauth2_scheme`.
2. :meth:`AuthGuard.verify` validates signature, issuer, audience, expiry, and
   tenant trust → :class:`~forge_core.security.IdentityContext`.
3. The identity is mapped to the service-local
   :class:`forge_core.domain.User` and stored on ``request.state``.

Dev mode (``auth.enabled=False``) skips verification and synthesizes a fixed
local user — the passthrough the base relies on when auth is off.

It depends only on the standard library, ``pydantic``, ``httpx`` and
``PyJWT`` — no weld, and no hard dependency on the optional platform-auth SDK.
At ``auth.mode=generate`` the platform-auth SDK + middleware fragment enrich /
override this stack (the FORGE:APP_POST_CONFIGURE rebind swaps the issuer),
but the always-shipped base never imports it. The module-level
``build_auth_guard`` symbol is the rebinding seam those providers patch.

The scope checker is registry-free (no hardcoded service enum) and the signing
algorithm defaults to ES256 but is configurable; provider-specific concerns
(on-behalf-of ``act`` chains, revocation, the Strive scope graph) live in the
optional platform-auth layer, not here.
"""

from forge_core.security.auth import (
    AuthenticatedUser,
    OptionalUser,
    authenticate_request,
    extract_token,
    get_auth_bundle_from_state,
    get_current_user,
    get_optional_user,
    initialize_auth,
    is_dev_mode,
    oauth2_scheme,
    set_auth_context,
    user_from_identity,
)
from forge_core.security.exceptions import (
    AuthError,
    InvalidToken,
    IssuerNotTrusted,
    ScopeRequired,
    TenantSuspended,
    TokenExpired,
)
from forge_core.security.guard import (
    DEFAULT_ALGORITHMS,
    AuthGuard,
)
from forge_core.security.identity import IdentityContext
from forge_core.security.jwks import JWKSCache
from forge_core.security.platform_auth_setup import (
    AuthGuardBundle,
    build_auth_guard,
    issuer_url,
    jwks_uri,
)
from forge_core.security.scopes import scope_satisfies
from forge_core.security.trust import (
    InMemoryIssuerTrustMap,
    IssuerTrustMap,
    TenantTrust,
)

__all__ = [
    "DEFAULT_ALGORITHMS",
    "AuthError",
    "AuthGuard",
    "AuthGuardBundle",
    "AuthenticatedUser",
    "IdentityContext",
    "InMemoryIssuerTrustMap",
    "InvalidToken",
    "IssuerNotTrusted",
    "IssuerTrustMap",
    "JWKSCache",
    "OptionalUser",
    "ScopeRequired",
    "TenantSuspended",
    "TenantTrust",
    "TokenExpired",
    "authenticate_request",
    "build_auth_guard",
    "extract_token",
    "get_auth_bundle_from_state",
    "get_current_user",
    "get_optional_user",
    "initialize_auth",
    "is_dev_mode",
    "issuer_url",
    "jwks_uri",
    "oauth2_scheme",
    "scope_satisfies",
    "set_auth_context",
    "user_from_identity",
]
