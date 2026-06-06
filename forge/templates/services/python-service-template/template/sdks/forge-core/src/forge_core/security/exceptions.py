"""Exception hierarchy for the generic security layer.

Every exception carries a stable ``reason`` slug and an HTTP-equivalent
``status_code`` so callers can map them directly to RFC 7807 problem
responses without sniffing the type tree. The slugs are part of the public
contract — clients dispatch on them.

This is the *generic* set the base verifier needs. Optional auth providers
(the platform-auth SDK shipped at ``auth.mode=generate``) bring their own,
richer hierarchy; this one keeps the always-shipped base self-contained.
"""

from __future__ import annotations

from typing import Any


class AuthError(Exception):
    """Root of all auth failures raised by the security layer.

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


class IssuerNotTrusted(AuthError):
    """Token's ``iss`` claim does not match the tenant's expected issuer."""

    reason = "issuer_not_trusted"
    status_code = 401


class TenantSuspended(AuthError):
    """Tenant is suspended; no requests for that tenant are accepted."""

    reason = "tenant_suspended"
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


__all__ = [
    "AuthError",
    "InvalidToken",
    "IssuerNotTrusted",
    "ScopeRequired",
    "TenantSuspended",
    "TokenExpired",
]
