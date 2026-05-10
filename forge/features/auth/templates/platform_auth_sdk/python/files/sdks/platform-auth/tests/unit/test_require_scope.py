"""require_scope dependency factory tests."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from platform_auth.auth_guard import require_scope
from platform_auth.exceptions import InvalidToken, ScopeRequired
from platform_auth.identity import IdentityContext
from platform_auth.scopes import Scope
from platform_auth.testing import (
    DEFAULT_TEST_TENANT_ID,
    TestAuthEnvironment,
    bearer_headers,
)


def _request_with_identity(identity: IdentityContext) -> Any:
    return SimpleNamespace(state=SimpleNamespace(identity=identity))


def _identity(*scopes: str) -> IdentityContext:
    return IdentityContext(
        tenant_id=DEFAULT_TEST_TENANT_ID,
        subject="user-1",
        scopes=frozenset(scopes),
    )


class TestRequireScopeBasics:
    async def test_satisfied_returns_identity(self):
        dep = require_scope("workflow:read")
        identity = _identity("workflow:read")
        result = await dep(_request_with_identity(identity))
        assert result is identity

    async def test_unsatisfied_raises_scope_required(self):
        dep = require_scope("workflow:write")
        identity = _identity("workflow:read")
        with pytest.raises(ScopeRequired) as exc_info:
            await dep(_request_with_identity(identity))
        assert exc_info.value.missing_scopes == frozenset({"workflow:write"})

    async def test_no_required_scopes_acts_as_authentication_only_check(self):
        dep = require_scope()
        identity = _identity()
        result = await dep(_request_with_identity(identity))
        assert result is identity

    async def test_multiple_required_scopes_all_must_be_present(self):
        dep = require_scope("workflow:read", "knowledge:read")
        identity = _identity("workflow:read")
        with pytest.raises(ScopeRequired) as exc_info:
            await dep(_request_with_identity(identity))
        # Only the missing one is in missing_scopes.
        assert exc_info.value.missing_scopes == frozenset({"knowledge:read"})

    async def test_hierarchy_aware(self):
        # A holder of `workflow:*` satisfies `workflow:read`.
        dep = require_scope("workflow:read")
        identity = _identity("workflow:*")
        result = await dep(_request_with_identity(identity))
        assert result is identity


class TestScopeEnumAcceptance:
    async def test_accepts_scope_enum_member(self):
        dep = require_scope(Scope.WORKFLOW_READ)
        identity = _identity("workflow:read")
        result = await dep(_request_with_identity(identity))
        assert result is identity

    async def test_mix_of_enum_and_string(self):
        dep = require_scope(Scope.WORKFLOW_READ, "knowledge:read")
        identity = _identity("workflow:read", "knowledge:read")
        result = await dep(_request_with_identity(identity))
        assert result is identity


class TestMissingIdentity:
    async def test_no_identity_on_state_fails_closed(self):
        """If AuthGuard didn't run (or didn't bind identity), the dependency
        must fail closed rather than letting an unauthenticated request
        through."""
        dep = require_scope("workflow:read")
        request = SimpleNamespace(state=SimpleNamespace())
        with pytest.raises(InvalidToken, match="no verified identity"):
            await dep(request)

    async def test_state_without_identity_attr(self):
        dep = require_scope()
        # Some test doubles might not even create state.
        request = SimpleNamespace(state=SimpleNamespace())
        with pytest.raises(InvalidToken):
            await dep(request)


class TestEndToEndWithAuthGuard:
    """Verify require_scope plays nicely with AuthGuard's request.state contract."""

    async def test_chain_after_auth_guard(self, auth_env: TestAuthEnvironment):
        token = auth_env.token(scopes="workflow:read")
        request = SimpleNamespace(headers=bearer_headers(token), state=SimpleNamespace())
        # Step 1: AuthGuard runs and stashes identity.
        await auth_env.auth_guard(request)
        # Step 2: require_scope inspects request.state.identity.
        dep = require_scope("workflow:read")
        identity = await dep(request)
        assert identity.subject == "test-user-1"

    async def test_chain_rejects_when_token_lacks_scope(self, auth_env: TestAuthEnvironment):
        token = auth_env.token(scopes="profile:read")
        request = SimpleNamespace(headers=bearer_headers(token), state=SimpleNamespace())
        await auth_env.auth_guard(request)
        dep = require_scope("workflow:write")
        with pytest.raises(ScopeRequired):
            await dep(request)
