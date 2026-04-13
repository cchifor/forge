from abc import ABC, abstractmethod
from typing import Any

from fastapi.security import OAuth2AuthorizationCodeBearer

from service.domain.config import AuthConfig


class AuthProvider(ABC):
    def __init__(self, config: AuthConfig):
        self.config = config

    @abstractmethod
    def get_swagger_scheme(self) -> OAuth2AuthorizationCodeBearer | None:
        pass

    @abstractmethod
    def validate_token(self, token: str) -> dict[str, Any]:
        pass
