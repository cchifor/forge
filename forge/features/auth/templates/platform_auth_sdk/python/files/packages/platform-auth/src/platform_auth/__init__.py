"""Identity, RBAC, and S2S auth primitives for the platform.

The public surface is intentionally small. Everything not listed below is an
implementation detail and may change without warning.
"""

from platform_auth.auth_guard import AuthGuard, require_scope
from platform_auth.exceptions import (
    ActorNotAuthorized,
    AuthError,
    InvalidToken,
    IssuerNotTrusted,
    S2SAuthError,
    ScopeRequired,
    TenantSuspended,
    TokenExpired,
    TokenRevoked,
)
from platform_auth.identity import IdentityContext
from platform_auth.jwks import JWKSCache
from platform_auth.may_act import (
    AllowAllMayActPolicy,
    MayActPolicy,
    StaticMayActPolicy,
)
from platform_auth.revocation import RevocationStore
from platform_auth.s2s_client import S2SClient
from platform_auth.scopes import Scope, scope_satisfies
from platform_auth.trust import (
    CachingIssuerTrustMap,
    InMemoryIssuerTrustMap,
    IssuerTrustMap,
    TenantTrust,
)

__all__ = [
    "ActorNotAuthorized",
    "AllowAllMayActPolicy",
    "AuthError",
    "AuthGuard",
    "CachingIssuerTrustMap",
    "IdentityContext",
    "InMemoryIssuerTrustMap",
    "InvalidToken",
    "IssuerNotTrusted",
    "IssuerTrustMap",
    "JWKSCache",
    "MayActPolicy",
    "RevocationStore",
    "S2SAuthError",
    "S2SClient",
    "Scope",
    "ScopeRequired",
    "StaticMayActPolicy",
    "TenantSuspended",
    "TenantTrust",
    "TokenExpired",
    "TokenRevoked",
    "require_scope",
    "scope_satisfies",
]
