"""Development auth provider that bypasses real authentication.

Returns a configurable fake user payload so the service can run
without a Keycloak (or any other IdP) instance.
"""

import logging

from fastapi.security import OAuth2AuthorizationCodeBearer

from service.security.base import AuthProvider

_logger = logging.getLogger(__name__)

_DEV_USER_PAYLOAD = {
    "sub": "00000000-0000-0000-0000-000000000001",
    "email": "dev@localhost",
    "preferred_username": "dev-user",
    "given_name": "Dev",
    "family_name": "User",
    "realm_access": {"roles": ["admin", "user"]},
    "azp": "dev-client",
    "customer_id": "00000000-0000-0000-0000-000000000001",
    "org_id": None,
}


class DevAuthProvider(AuthProvider):
    """Always returns a fake user — for local development only."""

    def get_swagger_scheme(self) -> OAuth2AuthorizationCodeBearer | None:
        return None

    def validate_token(self, token: str) -> dict:
        _logger.debug("DevAuthProvider: bypassing token validation")
        return _DEV_USER_PAYLOAD.copy()
