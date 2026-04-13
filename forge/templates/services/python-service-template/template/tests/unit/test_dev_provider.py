"""Tests for service.security.providers.dev."""

from service.domain.config import AuthConfig
from service.security.providers.dev import DevAuthProvider

_TEST_AUTH_CONFIG = AuthConfig(
    server_url="http://localhost:8080",
    realm="test",
    client_id="test-client",
    client_secret="secret",
)


class TestDevAuthProvider:
    def setup_method(self):
        self.provider = DevAuthProvider(config=_TEST_AUTH_CONFIG)

    def test_swagger_scheme_is_none(self):
        assert self.provider.get_swagger_scheme() is None

    def test_validate_token_returns_payload(self):
        payload = self.provider.validate_token("any-token")
        assert isinstance(payload, dict)

    def test_payload_has_required_fields(self):
        payload = self.provider.validate_token("")
        assert "sub" in payload
        assert "email" in payload
        assert "customer_id" in payload
        assert "realm_access" in payload

    def test_returns_copy(self):
        p1 = self.provider.validate_token("")
        p2 = self.provider.validate_token("")
        assert p1 == p2
        assert p1 is not p2
