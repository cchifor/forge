"""Security-headers middleware.

Adds a conservative set of response headers that mitigate common browser-side
attack classes. Defaults are safe for APIs served from a Traefik-fronted stack;
tune CSP/HSTS when this service also serves HTML.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

_DEFAULT_HEADERS: dict[str, str] = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "accelerometer=(), camera=(), geolocation=(), microphone=()",
    # CSP restricted to same-origin by default. Relax for HTML/asset-serving services.
    "Content-Security-Policy": "default-src 'self'; frame-ancestors 'none'",
    # HSTS: send only when the request arrived over TLS. Browsers ignore HSTS
    # over plain HTTP anyway, but we avoid noise in the header set.
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Inject standard security headers into every response."""

    def __init__(
        self,
        app,
        *,
        extra_headers: dict[str, str] | None = None,
        hsts_max_age: int = 31536000,
    ):
        super().__init__(app)
        self._headers = dict(_DEFAULT_HEADERS)
        if extra_headers:
            self._headers.update(extra_headers)
        self._hsts_max_age = hsts_max_age

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        for name, value in self._headers.items():
            response.headers.setdefault(name, value)
        if request.url.scheme == "https":
            response.headers.setdefault(
                "Strict-Transport-Security",
                f"max-age={self._hsts_max_age}; includeSubDomains",
            )
        return response
