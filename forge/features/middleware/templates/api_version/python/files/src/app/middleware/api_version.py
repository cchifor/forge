"""API versioning and deprecation middleware.

Adds standard headers to communicate API version lifecycle to clients,
following RFC 8594 (The Sunset HTTP Header Field) and the IETF
Deprecation header draft.

Headers set on responses:
    API-Version         Current API version (e.g. ``v1``).
    Deprecation         ISO 8601 date when this version was deprecated.
    Sunset              ISO 8601 date when this version will be removed.
    Link                URL to migration guide (rel=sunset).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware


class ApiVersionMiddleware(BaseHTTPMiddleware):
    """Injects API version and optional deprecation/sunset headers.

    Parameters
    ----------
    current_version : str
        Active version string (e.g. ``"v1"``).
    deprecated_at : str | None
        ISO 8601 date when this version was deprecated (``None`` = not deprecated).
    sunset_at : str | None
        ISO 8601 date when this version will be removed (``None`` = no sunset).
    sunset_link : str | None
        URL to migration documentation.
    """

    def __init__(
        self,
        app,
        *,
        current_version: str = "v1",
        deprecated_at: str | None = None,
        sunset_at: str | None = None,
        sunset_link: str | None = None,
    ) -> None:
        super().__init__(app)
        self.current_version = current_version
        self.deprecated_at = deprecated_at
        self.sunset_at = sunset_at
        self.sunset_link = sunset_link

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)

        response.headers["API-Version"] = self.current_version

        if self.deprecated_at:
            response.headers["Deprecation"] = self.deprecated_at

        if self.sunset_at:
            response.headers["Sunset"] = self.sunset_at

        if self.sunset_link:
            response.headers["Link"] = f'<{self.sunset_link}>; rel="sunset"'

        return response
