"""Security headers middleware.

Sets recommended security headers on every HTTP response to protect
against common web vulnerabilities (clickjacking, MIME sniffing, etc.).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, *, hsts: bool = True, csp: str | None = None) -> None:
        super().__init__(app)
        self.hsts = hsts
        self.csp = csp or "default-src 'self'; frame-ancestors 'none'"

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)

        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = (
            "camera=(), microphone=(), geolocation=()"
        )
        response.headers["Content-Security-Policy"] = self.csp

        if self.hsts:
            forwarded_proto = request.headers.get("x-forwarded-proto", "")
            if forwarded_proto == "https":
                response.headers["Strict-Transport-Security"] = (
                    "max-age=31536000; includeSubDomains; preload"
                )

        return response
