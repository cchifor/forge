"""Contract tests for the forge-core domain primitives.

The :class:`Account` scoping members, the :class:`User` claim shape and the
:class:`AuthConfig` field set + derived endpoint URLs are part of the public
contract (the persistence layer and the security layer dispatch on them), so
they're pinned here against an accidental reshape.
"""

from __future__ import annotations

import uuid

import pytest

from forge_core.domain import Account, AuthConfig, User, UserRole, context
from forge_core.persistence import AccountProtocol


class TestUserRole:
    def test_is_a_str_enum_with_the_generic_trichotomy(self) -> None:
        assert {r.value for r in UserRole} == {"admin", "user", "read_only"}

    def test_values_are_lowercase_member_names(self) -> None:
        assert UserRole.ADMIN == "admin"
        assert UserRole.READ_ONLY == "read_only"


class TestAccount:
    def test_coerces_string_ids_to_uuid(self) -> None:
        cid = "00000000-0000-0000-0000-000000000001"
        uid = "00000000-0000-0000-0000-000000000002"
        account = Account(customer_id=cid, user_id=uid)
        assert account.customer_id == uuid.UUID(cid)
        assert account.user_id == uuid.UUID(uid)

    def test_accepts_uuid_instances_unchanged(self) -> None:
        cid = uuid.uuid4()
        account = Account(customer_id=cid, user_id=None)
        assert account.customer_id is cid

    def test_none_ids_stay_none(self) -> None:
        account = Account(customer_id=None, user_id=None)
        assert account.customer_id is None
        assert account.user_id is None

    def test_non_uuid_value_degrades_to_none(self) -> None:
        # A machine identity whose ``sub`` is a client-id, not a UUID.
        account = Account(customer_id="tenant-1", user_id="svc-integration")
        assert account.customer_id is None
        assert account.user_id is None

    def test_default_role_is_user_and_not_admin(self) -> None:
        account = Account(customer_id=None, user_id=None)
        assert account.role is UserRole.USER
        assert account.is_admin() is False

    def test_admin_role_reports_admin(self) -> None:
        account = Account(customer_id=None, user_id=None, role=UserRole.ADMIN)
        assert account.is_admin() is True

    def test_read_only_is_not_admin(self) -> None:
        account = Account(customer_id=None, user_id=None, role=UserRole.READ_ONLY)
        assert account.is_admin() is False

    def test_satisfies_persistence_account_protocol(self) -> None:
        account = Account(customer_id=uuid.uuid4(), user_id=uuid.uuid4())
        assert isinstance(account, AccountProtocol)


class TestUser:
    def _minimal(self, **overrides: object) -> User:
        data: dict[str, object] = {
            "id": "u1",
            "username": "alice",
            "email": "alice@example.com",
            "first_name": "Alice",
            "last_name": "Smith",
            "roles": ["user"],
            "customer_id": "c1",
            "token": {"sub": "u1"},
        }
        data.update(overrides)
        return User(**data)  # type: ignore[arg-type]

    def test_minimal_construction_defaults(self) -> None:
        user = self._minimal()
        assert user.org_id is None
        assert user.service_account is False
        assert user.token == {"sub": "u1"}

    def test_carries_optional_org_and_service_account(self) -> None:
        user = self._minimal(org_id="org-9", service_account=True)
        assert user.org_id == "org-9"
        assert user.service_account is True

    def test_required_fields_enforced(self) -> None:
        with pytest.raises(Exception):  # noqa: B017 - pydantic ValidationError
            User(id="u1")  # type: ignore[call-arg]


class TestAuthConfig:
    def _cfg(self, **overrides: object) -> AuthConfig:
        data: dict[str, object] = {
            "server_url": "http://localhost:8080",
            "client_id": "my-service",
        }
        data.update(overrides)
        return AuthConfig(**data)  # type: ignore[arg-type]

    def test_defaults(self) -> None:
        cfg = self._cfg()
        assert cfg.enabled is True
        assert cfg.realm == "master"
        assert cfg.client_secret is None
        assert cfg.audience == "service-api"

    def test_server_url_and_client_id_required(self) -> None:
        with pytest.raises(Exception):  # noqa: B017 - pydantic ValidationError
            AuthConfig()  # type: ignore[call-arg]

    def test_auth_and_token_urls_derive_from_server_and_realm(self) -> None:
        cfg = self._cfg(server_url="http://kc:8080", realm="demo")
        base = "http://kc:8080/realms/demo/protocol/openid-connect"
        assert cfg.auth_url == f"{base}/auth"
        assert cfg.token_url == f"{base}/token"

    def test_trailing_slash_on_server_url_is_normalized(self) -> None:
        cfg = self._cfg(server_url="http://kc:8080/", realm="r")
        assert cfg.auth_url == "http://kc:8080/realms/r/protocol/openid-connect/auth"

    def test_carries_client_secret_and_audience(self) -> None:
        cfg = self._cfg(client_secret="s3cr3t", audience="other-api")
        assert cfg.client_secret == "s3cr3t"
        assert cfg.audience == "other-api"


class TestContext:
    def test_set_and_read_back(self) -> None:
        tokens = context.set_context("c1", "u1", "slug-1")
        try:
            assert context.get_customer_id() == "c1"
            assert context.get_user_id() == "u1"
            assert context.get_tenant_slug() == "slug-1"
        finally:
            context.reset_context(tokens)

    def test_getters_raise_when_unset(self) -> None:
        tokens = context.set_context("c1", "u1")
        context.reset_context(tokens)
        with pytest.raises(ValueError):
            context.get_customer_id()
        with pytest.raises(ValueError):
            context.get_user_id()

    def test_tenant_slug_defaults_to_none(self) -> None:
        tokens = context.set_context("c1", "u1")
        try:
            assert context.get_tenant_slug() is None
        finally:
            context.reset_context(tokens)

    def test_reset_with_two_tokens_is_backwards_compatible(self) -> None:
        # A caller that hand-rolls a two-token list (pre tenant_slug) must
        # still reset cleanly without an IndexError.
        tokens = context.set_context("c1", "u1", "slug")
        context.reset_context(tokens[:2])
        assert context.get_tenant_slug() == "slug"
        # clean up the leaked slug binding
        context.tenant_slug_context.set(None)
