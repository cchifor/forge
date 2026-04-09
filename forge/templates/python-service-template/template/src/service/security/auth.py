import asyncio
import logging
from typing import Annotated, cast

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.datastructures import Headers
from fastapi.openapi.models import OAuth2 as OAuth2Model
from fastapi.security import OAuth2AuthorizationCodeBearer

from service.core import context
from service.domain.auth_schema import TokenPayload
from service.domain.user import User
from service.security.base import AuthProvider

_logger = logging.getLogger(__name__)

oauth2_scheme = OAuth2AuthorizationCodeBearer(
    authorizationUrl="http://placeholder",
    tokenUrl="http://placeholder",
    auto_error=False,
)

_STATE_KEY = "auth_provider"


def initialize_auth(app: FastAPI, provider: AuthProvider, auth_url: str, token_url: str) -> None:
    setattr(app.state, _STATE_KEY, provider)

    if hasattr(oauth2_scheme, "model"):
        model = cast(OAuth2Model, oauth2_scheme.model)
        if model.flows.authorizationCode:
            model.flows.authorizationCode.authorizationUrl = auth_url
            model.flows.authorizationCode.tokenUrl = token_url

    _logger.info(f"Auth initialized. Provider: {provider.__class__.__name__}")


def get_auth_provider_from_state(request: Request) -> AuthProvider:
    provider = getattr(request.app.state, _STATE_KEY, None)
    if not provider:
        raise RuntimeError("Auth module not initialized. Call initialize_auth() in lifespan.")
    return provider


async def extract_token(request: Request) -> str | None:
    return await oauth2_scheme(request)


def hydrate_user(payload: TokenPayload, headers: Headers) -> User:
    user = User(
        id=payload.sub,
        username=payload.preferred_username or "unknown",
        email=payload.email or "",
        first_name=payload.given_name or "",
        last_name=payload.family_name or "",
        roles=payload.realm_access.roles,
        customer_id=payload.customer_id or payload.sub,
        org_id=payload.org_id,
        token=payload.model_dump(),
    )

    if payload.azp == "internal-service-client":
        user.service_account = True
        if c_id := headers.get("x-customer-id"):
            user.customer_id = c_id

    return user


async def authenticate_request(request: Request) -> User | None:
    provider = get_auth_provider_from_state(request)

    # ── Gatekeeper ForwardAuth headers (gateway already validated the token) ──
    gk_user_id = request.headers.get("x-gatekeeper-user-id")
    if gk_user_id:
        user = User(
            id=gk_user_id,
            username=request.headers.get("x-gatekeeper-email", "unknown"),
            email=request.headers.get("x-gatekeeper-email", ""),
            first_name="",
            last_name="",
            roles=[r for r in request.headers.get("x-gatekeeper-roles", "").split(",") if r],
            customer_id=gk_user_id,
            org_id=None,
            token={},
        )
        request.state.user = user
        return user

    # ── Bearer token (direct API access / Swagger) ──
    token = await extract_token(request)

    if not token:
        # If using DevAuthProvider (auth disabled), auto-authenticate
        from service.security.providers.dev import DevAuthProvider

        if isinstance(provider, DevAuthProvider):
            raw_payload = provider.validate_token("")
            payload = TokenPayload(**raw_payload)
            user = hydrate_user(payload, request.headers)
            request.state.user = user
            return user
        return None

    try:
        raw_payload = await asyncio.to_thread(provider.validate_token, token)
        payload = TokenPayload(**raw_payload)
        user = hydrate_user(payload, request.headers)
        request.state.user = user
        return user
    except Exception as e:
        _logger.warning(f"Auth failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        ) from e


async def _get_user_dependency(
    request: Request, token: Annotated[str | None, Depends(oauth2_scheme)]
) -> User | None:
    return await authenticate_request(request)


async def set_auth_context(
    user: Annotated[User | None, Depends(_get_user_dependency)],
) -> None:
    if user:
        context.set_context(customer_id=user.customer_id, user_id=user.id)
    else:
        context.set_context(customer_id="public", user_id="anonymous")


async def get_current_user(
    user: Annotated[User | None, Depends(_get_user_dependency)],
    _: None = Depends(set_auth_context),
) -> User:
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    return user


async def get_optional_user(
    user: Annotated[User | None, Depends(_get_user_dependency)],
    _: None = Depends(set_auth_context),
) -> User | None:
    return user


AuthenticatedUser = Annotated[User, Depends(get_current_user)]
OptionalUser = Annotated[User | None, Depends(get_optional_user)]
