"""Tests for service.security.auth."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI, HTTPException
from starlette.datastructures import Headers

from service.domain.auth_schema import KeycloakRealmAccess, TokenPayload
from service.domain.user import User
from service.security.auth import (
    get_auth_provider_from_state,
    hydrate_user,
    initialize_auth,
    set_auth_context,
)
from service.domain.config import AuthConfig
from service.security.providers.dev import DevAuthProvider

_TEST_AUTH_CONFIG = AuthConfig(
    server_url="http://localhost:8080",
    realm="test",
    client_id="test-client",
    client_secret="secret",
)


class TestInitializeAuth:
    def test_sets_provider_on_state(self):
        app = FastAPI()
        provider = DevAuthProvider(config=_TEST_AUTH_CONFIG)
        initialize_auth(app, provider, "http://auth", "http://token")
        assert getattr(app.state, "auth_provider") is provider


class TestGetAuthProviderFromState:
    def test_returns_provider(self):
        request = MagicMock()
        request.app.state.auth_provider = DevAuthProvider(config=_TEST_AUTH_CONFIG)
        provider = get_auth_provider_from_state(request)
        assert isinstance(provider, DevAuthProvider)

    def test_raises_when_not_initialized(self):
        request = MagicMock()
        request.app.state = MagicMock(spec=[])  # no auth_provider attr
        with pytest.raises(RuntimeError, match="not initialized"):
            get_auth_provider_from_state(request)


class TestHydrateUser:
    def _make_payload(self, **overrides):
        defaults = {
            "sub": "user-1",
            "preferred_username": "testuser",
            "email": "test@example.com",
            "given_name": "Test",
            "family_name": "User",
            "realm_access": KeycloakRealmAccess(roles=["user"]),
            "azp": "my-client",
            "customer_id": "cust-1",
            "org_id": None,
        }
        defaults.update(overrides)
        return TokenPayload(**defaults)

    def test_basic_hydration(self):
        payload = self._make_payload()
        user = hydrate_user(payload, Headers())
        assert user.id == "user-1"
        assert user.username == "testuser"
        assert user.customer_id == "cust-1"
        assert user.roles == ["user"]

    def test_service_account_flag(self):
        payload = self._make_payload(azp="internal-service-client")
        user = hydrate_user(payload, Headers())
        assert user.service_account is True

    def test_service_account_customer_override(self):
        payload = self._make_payload(azp="internal-service-client")
        headers = Headers({"x-customer-id": "override-cust"})
        user = hydrate_user(payload, headers)
        assert user.customer_id == "override-cust"

    def test_fallback_customer_id(self):
        payload = self._make_payload(customer_id=None)
        user = hydrate_user(payload, Headers())
        assert user.customer_id == payload.sub


class TestSetAuthContext:
    async def test_sets_context_with_user(self):
        from service.core.context import get_customer_id, get_user_id
        user = User(
            id="u1", username="test", email="t@t.com",
            first_name="T", last_name="U", roles=["user"],
            customer_id="c1", org_id=None, token={},
        )
        await set_auth_context(user)
        assert get_customer_id() == "c1"
        assert get_user_id() == "u1"

    async def test_sets_public_without_user(self):
        from service.core.context import get_customer_id, get_user_id
        await set_auth_context(None)
        assert get_customer_id() == "public"
        assert get_user_id() == "anonymous"
