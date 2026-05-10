"""Exception hierarchy for platform-auth.

Every exception carries a stable ``reason`` slug and an HTTP-equivalent
``status_code`` so callers can map them directly to RFC 7807 problem
responses or gRPC ``Status`` codes without sniffing the type tree.

The slugs are part of the public contract — clients dispatch on them.
"""

from __future__ import annotations

from typing import Any


class AuthError(Exception):
    """Root of all auth failures raised by the SDK.

    ``reason`` is a short snake_case slug that is part of the public API;
    clients dispatch on it. ``detail`` is human-readable extra context and
    must not leak secrets. ``status_code`` is the HTTP equivalent.
    """

    reason: str = "auth_error"
    status_code: int = 401

    def __init__(self, detail: str | None = None, **extra: Any) -> None:
        message = detail if detail is not None else self.reason
        super().__init__(message)
        self.detail = detail
        self.extra = extra


class InvalidToken(AuthError):
    """Token is malformed, has a bad signature, or is missing required claims."""

    reason = "invalid_token"
    status_code = 401


class TokenExpired(AuthError):
    """Token's ``exp`` claim is in the past (or ``nbf`` is in the future)."""

    reason = "token_expired"
    status_code = 401


class TokenRevoked(AuthError):
    """Token's ``jti`` is on the revocation denylist."""

    reason = "token_revoked"
    status_code = 401


class IssuerNotTrusted(AuthError):
    """Token's ``iss`` claim does not match the tenant's expected issuer.

    Raised when the hybrid-realm trust map says the tenant should be issued
    tokens by issuer A but this token came from issuer B. Distinct from
    :class:`InvalidToken` because the token is otherwise structurally valid.
    """

    reason = "issuer_not_trusted"
    status_code = 401


class ActorNotAuthorized(AuthError):
    """The ``act`` chain contains a service not allowed to impersonate.

    Raised when an on-behalf-of token has an actor entry that violates the
    destination's ``may_act`` policy.
    """

    reason = "actor_not_authorized"
    status_code = 403


class ScopeRequired(AuthError):
    """The caller's scopes do not satisfy the endpoint's required scopes.

    ``missing_scopes`` lists the scopes that would have satisfied the
    requirement (any one of them); audit-log consumers use this to explain
    the denial.
    """

    reason = "scope_required"
    status_code = 403

    def __init__(
        self,
        missing_scopes: frozenset[str],
        detail: str | None = None,
    ) -> None:
        super().__init__(detail=detail, missing_scopes=missing_scopes)
        self.missing_scopes = missing_scopes


class TenantSuspended(AuthError):
    """Tenant is suspended; no requests for that tenant are accepted.

    Distinct from :class:`InvalidToken` so clients can differentiate "your
    tenant is paused" from "your token is bad".
    """

    reason = "tenant_suspended"
    status_code = 403


class S2SAuthError(AuthError):
    """Outbound service-to-service authentication failed.

    Raised by :class:`platform_auth.S2SClient` when the token endpoint is
    unreachable, returns a non-2xx status, or yields a malformed response.
    Distinct from inbound errors because the failure is on our side: we
    could not obtain a token to forward, so the caller's request cannot
    proceed. ``503`` is the HTTP equivalent — this service depends on an
    upstream that is currently failing.
    """

    reason = "s2s_auth_error"
    status_code = 503
