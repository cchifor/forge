"""AuthContextMiddleware — verify the bearer token and bind identity.

Runs ``authenticate_request`` once per request and stashes the verified
:class:`platform_auth.IdentityContext` (and the translated ``User``) on
``request.state``. Downstream dependencies (``app.core.auth.get_gatekeeper_user``
et al.) read from there rather than re-running the verifier.

Health/metrics paths skip verification so probes work without auth.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from fastapi import HTTPException, Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from service.core import context
from service.security.auth import authenticate_request

log = logging.getLogger(__name__)

_DEFAULT_EXCLUDED_PATHS = {
    "/health",
    "/health/live",
    "/health/ready",
    "/metrics",
    "/docs",
    "/openapi.json",
    "/redoc",
}


class AuthContextMiddleware(BaseHTTPMiddleware):
    """Populate ``request.state.{user, identity}`` and tenant ContextVars."""

    def __init__(self, app, excluded_paths: set[str] | None = None) -> None:
        super().__init__(app)
        self._excluded = excluded_paths or _DEFAULT_EXCLUDED_PATHS

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if request.url.path in self._excluded:
            return await call_next(request)

        customer_token = user_token = None
        try:
            user = await authenticate_request(request)
        except HTTPException as exc:
            detail = exc.detail
            payload = detail if isinstance(detail, dict) else {"detail": str(detail)}
            return JSONResponse(
                status_code=exc.status_code,
                content=payload,
                headers=exc.headers or {},
            )

        if user is not None:
            customer_token = context.customer_id_context.set(user.customer_id)
            user_token = context.user_id_context.set(user.id)

        try:
            return await call_next(request)
        finally:
            if customer_token is not None:
                context.customer_id_context.reset(customer_token)
            if user_token is not None:
                context.user_id_context.reset(user_token)
