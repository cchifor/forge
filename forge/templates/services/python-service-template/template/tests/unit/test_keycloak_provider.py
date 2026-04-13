"""Unit tests for the Keycloak auth provider."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from pydantic import SecretStr

from service.security.base import AuthProvider


def _make_auth_config(**overrides):
    """Build a minimal AuthConfig-like mock."""
    from service.domain.config import AuthConfig

    defaults = {
        "server_url": "http://keycloak.local:8080",
        "realm": "test-realm",
        "client_id": "my-client",
        "client_secret": SecretStr("super-secret"),
        "enabled": True,
        "audience": "service-api",
    }
    defaults.update(overrides)
    return AuthConfig(**defaults)


class TestKeycloakProviderInit:
    """Construction and inheritance checks."""

    @patch(
        "service.security.providers.keycloak.KeycloakOpenID",
        autospec=True,
    )
    def test_inherits_auth_provider(self, mock_kc_cls):
        from service.security.providers.keycloak import (
            KeycloakProvider,
        )

        config = _make_auth_config()
        provider = KeycloakProvider(config)

        assert isinstance(provider, AuthProvider)

    @patch(
        "service.security.providers.keycloak.KeycloakOpenID",
        autospec=True,
    )
    def test_passes_config_to_keycloak_client(self, mock_kc_cls):
        from service.security.providers.keycloak import (
            KeycloakProvider,
        )

        config = _make_auth_config()
        KeycloakProvider(config)

        mock_kc_cls.assert_called_once_with(
            server_url=str(config.server_url),
            client_id="my-client",
            client_secret_key="super-secret",
            realm_name="test-realm",
        )


class TestValidateToken:
    """Token validation behaviour."""

    @patch(
        "service.security.providers.keycloak.KeycloakOpenID",
        autospec=True,
    )
    def test_returns_decoded_payload_on_success(self, mock_kc_cls):
        from service.security.providers.keycloak import (
            KeycloakProvider,
        )

        expected = {"sub": "user-1", "roles": ["admin"]}
        mock_kc_cls.return_value.decode_token.return_value = expected

        provider = KeycloakProvider(_make_auth_config())
        result = provider.validate_token("good-token")

        assert result == expected
        mock_kc_cls.return_value.decode_token.assert_called_once_with(
            "good-token", validate=False,
        )

    @patch(
        "service.security.providers.keycloak.KeycloakOpenID",
        autospec=True,
    )
    def test_raises_401_on_invalid_token(self, mock_kc_cls):
        from service.security.providers.keycloak import (
            KeycloakProvider,
        )

        mock_kc_cls.return_value.decode_token.side_effect = (
            Exception("bad signature")
        )

        provider = KeycloakProvider(_make_auth_config())

        with pytest.raises(HTTPException) as exc_info:
            provider.validate_token("bad-token")

        assert exc_info.value.status_code == 401
        assert exc_info.value.detail == "Invalid token"

    @patch(
        "service.security.providers.keycloak.KeycloakOpenID",
        autospec=True,
    )
    def test_401_includes_www_authenticate_header(self, mock_kc_cls):
        from service.security.providers.keycloak import (
            KeycloakProvider,
        )

        mock_kc_cls.return_value.decode_token.side_effect = (
            Exception("expired")
        )

        provider = KeycloakProvider(_make_auth_config())

        with pytest.raises(HTTPException) as exc_info:
            provider.validate_token("expired-token")

        assert exc_info.value.headers == {
            "WWW-Authenticate": "Bearer",
        }


class TestGetSwaggerScheme:
    """Swagger OAuth2 scheme generation."""

    @patch(
        "service.security.providers.keycloak.KeycloakOpenID",
        autospec=True,
    )
    def test_returns_oauth2_scheme_when_enabled(self, mock_kc_cls):
        from fastapi.security import OAuth2AuthorizationCodeBearer

        from service.security.providers.keycloak import (
            KeycloakProvider,
        )

        provider = KeycloakProvider(_make_auth_config(enabled=True))
        scheme = provider.get_swagger_scheme()

        assert isinstance(scheme, OAuth2AuthorizationCodeBearer)

    @patch(
        "service.security.providers.keycloak.KeycloakOpenID",
        autospec=True,
    )
    def test_returns_none_when_disabled(self, mock_kc_cls):
        from service.security.providers.keycloak import (
            KeycloakProvider,
        )

        provider = KeycloakProvider(
            _make_auth_config(enabled=False),
        )
        scheme = provider.get_swagger_scheme()

        assert scheme is None

    @patch(
        "service.security.providers.keycloak.KeycloakOpenID",
        autospec=True,
    )
    def test_scheme_urls_contain_realm(self, mock_kc_cls):
        from service.security.providers.keycloak import (
            KeycloakProvider,
        )

        provider = KeycloakProvider(_make_auth_config())
        scheme = provider.get_swagger_scheme()

        flows = scheme.model.flows
        auth_url = flows.authorizationCode.authorizationUrl
        token_url = flows.authorizationCode.tokenUrl
        assert "test-realm" in auth_url
        assert "test-realm" in token_url
