"""Tests for service-layer domain models (Account, User, AuthSchema, Config)."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from pydantic import SecretStr

from service.domain.account import Account, UserRole, _to_uuid
from service.domain.auth_schema import KeycloakRealmAccess, TokenPayload
from service.domain.config import AuthConfig
from service.domain.user import User


# -- Account -------------------------------------------------------------------


class TestAccount:
    def test_from_strings(self):
        cid = "00000000-0000-0000-0000-000000000001"
        uid = "00000000-0000-0000-0000-000000000002"
        acct = Account(customer_id=cid, user_id=uid)
        assert isinstance(acct.customer_id, UUID)
        assert isinstance(acct.user_id, UUID)
        assert acct.role == UserRole.USER

    def test_from_uuids(self):
        cid, uid = uuid4(), uuid4()
        acct = Account(customer_id=cid, user_id=uid, role=UserRole.ADMIN)
        assert acct.customer_id == cid
        assert acct.is_admin() is True

    def test_none_ids(self):
        acct = Account(customer_id=None, user_id=None)
        assert acct.customer_id is None
        assert acct.user_id is None

    def test_is_admin_false_for_user(self):
        acct = Account(customer_id=uuid4(), user_id=uuid4())
        assert acct.is_admin() is False


class TestUserRole:
    def test_values(self):
        assert set(UserRole) == {
            UserRole.ADMIN,
            UserRole.USER,
            UserRole.READ_ONLY,
        }


class TestToUuid:
    def test_none(self):
        assert _to_uuid(None) is None

    def test_string(self):
        uid = "12345678-1234-1234-1234-123456789abc"
        assert _to_uuid(uid) == UUID(uid)

    def test_uuid_passthrough(self):
        uid = uuid4()
        assert _to_uuid(uid) is uid


# -- User ----------------------------------------------------------------------


class TestUser:
    def test_instantiation(self):
        user = User(
            id="u1",
            username="alice",
            email="a@b.com",
            first_name="Alice",
            last_name="Smith",
            roles=["user"],
            customer_id="cust-1",
            token={"access_token": "xyz"},
        )
        assert user.username == "alice"
        assert user.org_id is None
        assert user.service_account is False

    def test_serialization(self):
        user = User(
            id="u1",
            username="bob",
            email="b@b.com",
            first_name="Bob",
            last_name="Jones",
            roles=["admin"],
            customer_id="c1",
            token={},
        )
        data = user.model_dump()
        assert data["username"] == "bob"
        assert data["service_account"] is False


# -- TokenPayload / KeycloakRealmAccess ----------------------------------------


class TestTokenPayload:
    def test_minimal(self):
        tp = TokenPayload(sub="sub-1")
        assert tp.sub == "sub-1"
        assert tp.email is None
        assert tp.realm_access.roles == []

    def test_extra_fields_ignored(self):
        tp = TokenPayload(sub="s", unknown_field="ignored")
        assert not hasattr(tp, "unknown_field")


# -- AuthConfig ----------------------------------------------------------------


class TestAuthConfig:
    def _make(self, **overrides):
        defaults = dict(
            server_url="https://auth.example.com",
            realm="myrealm",
            client_id="my-client",
            client_secret="s3cret",
        )
        defaults.update(overrides)
        return AuthConfig(**defaults)

    def test_defaults(self):
        cfg = self._make()
        assert cfg.enabled is True
        assert cfg.audience == "service-api"

    def test_auth_url(self):
        cfg = self._make()
        assert cfg.auth_url.endswith(
            "/realms/myrealm/protocol/openid-connect/auth"
        )

    def test_token_url(self):
        cfg = self._make()
        assert cfg.token_url.endswith(
            "/realms/myrealm/protocol/openid-connect/token"
        )

    def test_secret_serialization(self):
        cfg = self._make(client_secret="top-secret")
        data = cfg.model_dump()
        assert data["client_secret"] == "top-secret"
