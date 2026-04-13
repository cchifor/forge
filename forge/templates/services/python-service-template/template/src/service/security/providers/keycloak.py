import logging

from fastapi import HTTPException, status
from fastapi.security import OAuth2AuthorizationCodeBearer
from keycloak import KeycloakOpenID

from service.security.base import AuthProvider

_logger = logging.getLogger(__name__)


class KeycloakProvider(AuthProvider):
    def __init__(self, config):
        super().__init__(config)
        self._client = KeycloakOpenID(
            server_url=str(self.config.server_url),
            client_id=self.config.client_id,
            client_secret_key=self.config.client_secret.get_secret_value(),
            realm_name=self.config.realm,
        )

    def get_swagger_scheme(self) -> OAuth2AuthorizationCodeBearer | None:
        if not self.config.enabled:
            return None
        base_url = f"{self.config.server_url}/realms/{self.config.realm}/protocol/openid-connect"
        return OAuth2AuthorizationCodeBearer(
            authorizationUrl=f"{base_url}/auth",
            tokenUrl=f"{base_url}/token",
            auto_error=False,
        )

    def validate_token(self, token: str) -> dict:
        try:
            return self._client.decode_token(token, validate=False)
        except Exception as e:
            _logger.warning(f"Keycloak validation failed: {e}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token",
                headers={"WWW-Authenticate": "Bearer"},
            ) from e
