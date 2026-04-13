"""Tests for service.client.auth."""

import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from service.client.auth import ClientCredentialsAuth


class TestClientCredentialsAuth:
    def test_is_expired_initially(self):
        auth = ClientCredentialsAuth(
            token_url="http://auth/token",
            client_id="id",
            client_secret="secret",
        )
        assert auth.is_expired is True

    async def test_get_token_fetches(self):
        auth = ClientCredentialsAuth(
            token_url="http://auth/token",
            client_id="id",
            client_secret="secret",
        )
        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "access_token": "tok123",
            "expires_in": 300,
        }
        mock_client.post.return_value = mock_response

        token = await auth.get_token(mock_client)
        assert token == "tok123"
        mock_client.post.assert_called_once()

    async def test_get_token_caches(self):
        auth = ClientCredentialsAuth(
            token_url="http://auth/token",
            client_id="id",
            client_secret="secret",
        )
        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "access_token": "tok123",
            "expires_in": 300,
        }
        mock_client.post.return_value = mock_response

        await auth.get_token(mock_client)
        await auth.get_token(mock_client)
        assert mock_client.post.call_count == 1

    async def test_get_token_with_scopes(self):
        auth = ClientCredentialsAuth(
            token_url="http://auth/token",
            client_id="id",
            client_secret="secret",
            scopes=["read", "write"],
        )
        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "access_token": "tok",
            "expires_in": 300,
        }
        mock_client.post.return_value = mock_response

        await auth.get_token(mock_client)
        call_data = mock_client.post.call_args.kwargs.get(
            "data", mock_client.post.call_args[1].get("data", {})
        )
        assert call_data["scope"] == "read write"

    async def test_get_token_default_expiry(self):
        auth = ClientCredentialsAuth(
            token_url="http://auth/token",
            client_id="id",
            client_secret="secret",
        )
        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.json.return_value = {"access_token": "tok"}
        mock_client.post.return_value = mock_response

        await auth.get_token(mock_client)
        # Default expiry is 300s, so token should not be expired
        assert auth.is_expired is False


class TestFromKeycloak:
    def test_constructs_correct_url(self):
        auth = ClientCredentialsAuth.from_keycloak(
            server_url="http://keycloak:8080",
            realm="myrealm",
            client_id="app",
            client_secret="secret",
        )
        assert "myrealm" in auth._token_url
        assert "openid-connect/token" in auth._token_url

    def test_strips_trailing_slash(self):
        auth = ClientCredentialsAuth.from_keycloak(
            server_url="http://keycloak:8080/",
            realm="dev",
            client_id="app",
            client_secret="secret",
        )
        assert "//" not in auth._token_url.split("://", 1)[1]
