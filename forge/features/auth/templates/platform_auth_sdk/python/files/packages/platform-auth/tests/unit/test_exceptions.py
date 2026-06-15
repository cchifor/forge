"""Exception hierarchy contract tests.

The ``reason`` slugs and ``status_code`` values are part of the public API —
clients dispatch on them, RFC 7807 problem responses use them. Pinning them
here prevents accidental rename / status-bump in a refactor.
"""

from __future__ import annotations

import pytest

from platform_auth.exceptions import (
    ActorNotAuthorized,
    AuthError,
    InvalidToken,
    IssuerNotTrusted,
    ScopeRequired,
    TenantSuspended,
    TokenExpired,
    TokenRevoked,
)


class TestExceptionHierarchy:
    def test_every_specific_error_descends_from_AuthError(self):
        for exc_cls in (
            InvalidToken,
            TokenExpired,
            TokenRevoked,
            IssuerNotTrusted,
            ActorNotAuthorized,
            TenantSuspended,
        ):
            assert issubclass(exc_cls, AuthError)

    def test_AuthError_is_an_Exception(self):
        assert issubclass(AuthError, Exception)


class TestReasonSlugs:
    @pytest.mark.parametrize(
        ("exc_cls", "expected_reason"),
        [
            (AuthError, "auth_error"),
            (InvalidToken, "invalid_token"),
            (TokenExpired, "token_expired"),
            (TokenRevoked, "token_revoked"),
            (IssuerNotTrusted, "issuer_not_trusted"),
            (ActorNotAuthorized, "actor_not_authorized"),
            (TenantSuspended, "tenant_suspended"),
        ],
    )
    def test_reason_slug_is_pinned(self, exc_cls: type[AuthError], expected_reason: str):
        assert exc_cls.reason == expected_reason


class TestStatusCodes:
    @pytest.mark.parametrize(
        ("exc_cls", "expected_status"),
        [
            (AuthError, 401),
            (InvalidToken, 401),
            (TokenExpired, 401),
            (TokenRevoked, 401),
            (IssuerNotTrusted, 401),
            (ActorNotAuthorized, 403),
            (TenantSuspended, 403),
        ],
    )
    def test_status_code_is_pinned(self, exc_cls: type[AuthError], expected_status: int):
        assert exc_cls.status_code == expected_status


class TestScopeRequired:
    def test_carries_missing_scopes(self):
        missing = frozenset({"workflow:write", "workflow:admin"})
        exc = ScopeRequired(missing_scopes=missing)
        assert exc.missing_scopes == missing

    def test_status_and_reason(self):
        exc = ScopeRequired(missing_scopes=frozenset({"x:y"}))
        assert exc.reason == "scope_required"
        assert exc.status_code == 403

    def test_extra_kwargs_round_trip(self):
        missing = frozenset({"x:y"})
        exc = ScopeRequired(missing_scopes=missing, detail="needs write")
        assert exc.detail == "needs write"
        assert exc.missing_scopes == missing


class TestExceptionConstruction:
    def test_default_message_uses_reason(self):
        exc = InvalidToken()
        assert str(exc) == "invalid_token"

    def test_explicit_detail_replaces_message(self):
        exc = InvalidToken(detail="bad signature")
        assert str(exc) == "bad signature"
        assert exc.detail == "bad signature"

    def test_extra_kwargs_are_stored(self):
        exc = TokenExpired(detail="expired", expired_at="2026-05-02T00:00:00Z")
        assert exc.extra == {"expired_at": "2026-05-02T00:00:00Z"}
