"""IdentityContext value-object tests."""

from __future__ import annotations

from uuid import UUID

import pytest

from platform_auth.identity import IdentityContext

TENANT_A = UUID("11111111-1111-1111-1111-111111111111")
TENANT_B = UUID("22222222-2222-2222-2222-222222222222")


def _ident(
    *,
    tenant_id: UUID = TENANT_A,
    subject: str = "user-1",
    roles: frozenset[str] = frozenset(),
    scopes: frozenset[str] = frozenset(),
    actor: str | None = None,
    raw_claims=None,
) -> IdentityContext:
    return IdentityContext(
        tenant_id=tenant_id,
        subject=subject,
        roles=roles,
        scopes=scopes,
        actor=actor,
        raw_claims=raw_claims if raw_claims is not None else {},
    )


class TestImmutability:
    def test_identity_is_frozen(self):
        ident = _ident()
        with pytest.raises(AttributeError):
            ident.tenant_id = TENANT_B  # type: ignore[misc]

    def test_identity_is_hashable(self):
        ident = _ident(scopes=frozenset({"workflow:read"}))
        # Hash is required so the value can live in a set or dict key.
        hash(ident)

    def test_two_identities_with_same_primary_claims_are_equal(self):
        a = _ident(scopes=frozenset({"workflow:read"}))
        b = _ident(scopes=frozenset({"workflow:read"}))
        assert a == b
        assert hash(a) == hash(b)

    def test_raw_claims_difference_does_not_break_equality(self):
        # raw_claims is informational; identical primary fields → equal.
        a = _ident(raw_claims={"iat": 1})
        b = _ident(raw_claims={"iat": 2})
        assert a == b


class TestScopeHelpers:
    def test_has_scope_uses_hierarchy(self):
        ident = _ident(scopes=frozenset({"workflow:*"}))
        assert ident.has_scope("workflow:read")
        assert ident.has_scope("workflow:write")
        assert not ident.has_scope("knowledge:read")

    def test_has_any_scope(self):
        ident = _ident(scopes=frozenset({"knowledge:read"}))
        assert ident.has_any_scope("workflow:read", "knowledge:read")
        assert not ident.has_any_scope("workflow:read", "profile:read")

    def test_has_all_scopes(self):
        ident = _ident(scopes=frozenset({"workflow:read", "knowledge:read"}))
        assert ident.has_all_scopes("workflow:read", "knowledge:read")
        assert not ident.has_all_scopes("workflow:read", "profile:read")

    def test_has_scope_with_no_scopes(self):
        ident = _ident()
        assert not ident.has_scope("workflow:read")


class TestPlatformAdmin:
    def test_platform_admin_when_holding_support_read(self):
        ident = _ident(scopes=frozenset({IdentityContext.PLATFORM_SUPPORT_READ}))
        assert ident.is_platform_admin

    def test_platform_admin_when_holding_support_write(self):
        ident = _ident(scopes=frozenset({IdentityContext.PLATFORM_SUPPORT_WRITE}))
        assert ident.is_platform_admin

    def test_platform_admin_when_holding_super_wildcard(self):
        ident = _ident(scopes=frozenset({"*"}))
        assert ident.is_platform_admin

    def test_not_platform_admin_with_only_per_service_scopes(self):
        ident = _ident(scopes=frozenset({"workflow:admin", "knowledge:admin"}))
        assert not ident.is_platform_admin

    def test_constants_are_class_level_not_instance_fields(self):
        # If these were dataclass fields they'd be required constructor args
        # — verify they're true ClassVars.
        assert IdentityContext.PLATFORM_SUPPORT_READ == "platform:support:read"
        assert IdentityContext.PLATFORM_SUPPORT_WRITE == "platform:support:write"


class TestActor:
    def test_no_actor_means_first_party_token(self):
        ident = _ident()
        assert ident.actor is None
        assert not ident.is_actor

    def test_actor_set_means_on_behalf_of(self):
        ident = _ident(actor="svc-deepagent")
        assert ident.is_actor
        assert ident.actor == "svc-deepagent"


class TestDefaults:
    def test_roles_and_scopes_default_to_empty_frozenset(self):
        ident = _ident()
        assert ident.roles == frozenset()
        assert ident.scopes == frozenset()
        assert isinstance(ident.roles, frozenset)
        assert isinstance(ident.scopes, frozenset)

    def test_raw_claims_default_to_empty_mapping(self):
        ident = IdentityContext(tenant_id=TENANT_A, subject="user-1")
        assert dict(ident.raw_claims) == {}
