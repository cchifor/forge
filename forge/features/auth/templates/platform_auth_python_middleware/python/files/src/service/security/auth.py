"""Per-request authentication for HTTP endpoints.

The platform-wide identity model lives in :mod:`platform_auth`. This module
adapts that model to this service's request lifecycle:

* :func:`initialize_auth` plants the configured :class:`platform_auth.AuthGuard`
  on the FastAPI app at startup.
* :func:`authenticate_request` extracts the bearer token, asks the guard to
  verify it, and translates the resulting :class:`platform_auth.IdentityContext`
  into the service-local :class:`service.domain.user.User`. The User type is
  preserved because endpoints, repositories, and the audit middleware
  consume it directly.
* The legacy ``X-Gatekeeper-*`` plain-header trust path is gone — the
  bearer token is the only source of identity.

Dev mode (``auth.enabled=False``) skips verification and synthesizes a
fixed local User so a developer can run the service without an IdP. To
exercise the real verification path locally, set ``auth.enabled=True`` and
point JWKS at a local test issuer.
"""

from __future__ import annotations

import logging
from typing import Annotated, cast

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.datastructures import Headers
from fastapi.openapi.models import OAuth2 as OAuth2Model
from fastapi.security import OAuth2AuthorizationCodeBearer
from platform_auth import AuthError, IdentityContext

from forge_core.domain import context
from forge_core.domain.user import User
from service.security.platform_auth_setup import AuthGuardBundle

_logger = logging.getLogger(__name__)

oauth2_scheme = OAuth2AuthorizationCodeBearer(
    authorizationUrl="http://placeholder",
    tokenUrl="http://placeholder",
    auto_error=False,
)

_GUARD_KEY = "auth_guard_bundle"
_DEV_KEY = "auth_dev_mode"

_DEV_USER = User(
    id="00000000-0000-0000-0000-000000000001",
    username="dev-user",
    email="dev@localhost",
    first_name="Dev",
    last_name="User",
    roles=["admin", "user"],
    customer_id="00000000-0000-0000-0000-000000000001",
    org_id=None,
    token={},
)


def initialize_auth(
    app: FastAPI,
    *,
    bundle: AuthGuardBundle,
    auth_url: str,
    token_url: str,
    dev_mode: bool = False,
) -> None:
    """Register the :class:`AuthGuardBundle` and OIDC URLs on the app.

    ``dev_mode=True`` skips token verification entirely and serves a fixed
    local user for every request. Use only when ``auth.enabled=False``.
    """
    setattr(app.state, _GUARD_KEY, bundle)
    setattr(app.state, _DEV_KEY, dev_mode)

    if hasattr(oauth2_scheme, "model"):
        model = cast(OAuth2Model, oauth2_scheme.model)
        if model.flows.authorizationCode:
            model.flows.authorizationCode.authorizationUrl = auth_url
            model.flows.authorizationCode.tokenUrl = token_url

    _logger.info(
        "Auth initialized. audience=%s issuers=%s dev_mode=%s",
        bundle.guard.audience,
        sorted(bundle.jwks.registered_issuers()),
        dev_mode,
    )


def get_auth_bundle_from_state(request: Request) -> AuthGuardBundle:
    bundle = getattr(request.app.state, _GUARD_KEY, None)
    if bundle is None:
        raise RuntimeError("Auth not initialized. Call initialize_auth() in lifespan.")
    return bundle


def is_dev_mode(request: Request) -> bool:
    return bool(getattr(request.app.state, _DEV_KEY, False))


async def extract_token(request: Request) -> str | None:
    return await oauth2_scheme(request)


def user_from_identity(identity: IdentityContext, headers: Headers) -> User:
    """Translate a verified :class:`IdentityContext` into the service-local ``User``.

    Profile-specific claims (``email``, ``preferred_username``, given/family
    name) come from ``raw_claims``; absent claims default to empty strings to
    keep the schema stable.
    """
    claims = identity.raw_claims
    azp = claims.get("azp")
    return User(
        id=identity.subject,
        username=str(claims.get("preferred_username") or claims.get("email") or identity.subject),
        email=str(claims.get("email") or ""),
        first_name=str(claims.get("given_name") or ""),
        last_name=str(claims.get("family_name") or ""),
        roles=sorted(identity.roles),
        customer_id=str(identity.tenant_id),
        org_id=claims.get("org_id"),
        service_account=isinstance(azp, str) and azp.startswith("svc-"),
        token=dict(claims),
    )


async def authenticate_request(request: Request) -> User | None:
    """Verify the incoming request and return the authenticated ``User``.

    Returns ``None`` when no token is present (and dev mode is off); raises
    HTTP 401 when a token is present but invalid. Sets ``request.state.user``
    on success so downstream middleware (audit, observability) can pick it
    up without re-running verification.
    """
    bundle = get_auth_bundle_from_state(request)
    dev_mode = is_dev_mode(request)

    token = await extract_token(request)

    if not token:
        if dev_mode:
            request.state.user = _DEV_USER
            return _DEV_USER
        return None

    try:
        identity = await bundle.guard.verify(token)
    except AuthError as exc:
        _logger.warning(
            "auth_rejected",
            extra={"reason": exc.reason, "detail": exc.detail},
        )
        raise HTTPException(
            status_code=exc.status_code,
            detail={"reason": exc.reason, "detail": exc.detail or exc.reason},
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    user = user_from_identity(identity, request.headers)
    request.state.user = user
    request.state.identity = identity
    return user


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
