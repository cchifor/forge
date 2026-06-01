"""``weld.fastapi.security.auth`` — request-time auth helpers (matrix-CI stub)."""

from __future__ import annotations

from typing import Any


async def authenticate_request(*args: Any, **kwargs: Any) -> Any:
    """Stub. Real impl pulls a bearer token, verifies, returns IdentityContext."""
    return None


async def get_current_user(*args: Any, **kwargs: Any) -> Any:
    """Stub. Real impl raises HTTP 401 when no valid token is present; used as a
    router-level FastAPI dependency to gate /mcp. Permissive here so generated
    projects import + run their toolchains against the stub without standing up
    a real auth stack (router-level deps discard the return value)."""
    return None


def initialize_auth(*args: Any, **kwargs: Any) -> None:
    """Stub. Real impl wires the AuthGuardBundle into FastAPI app state."""


def get_auth_bundle_from_state(*args: Any, **kwargs: Any) -> Any:
    """Stub. Real impl reads ``AuthGuardBundle`` off ``request.app.state``."""
    return None


def is_dev_mode(*args: Any, **kwargs: Any) -> bool:
    return False


def user_from_identity(*args: Any, **kwargs: Any) -> Any:
    return None


async def extract_token(*args: Any, **kwargs: Any) -> str | None:
    return None


class _OAuth2Scheme:
    """Stub matching FastAPI's OAuth2PasswordBearer interface."""

    def __init__(self, *args: Any, **kwargs: Any) -> None: ...

    async def __call__(self, *args: Any, **kwargs: Any) -> str | None:
        return None


oauth2_scheme = _OAuth2Scheme()
