import logging
import time
from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

logger = logging.getLogger(__name__)


class AuditMiddleware(BaseHTTPMiddleware):
    """Records HTTP operations for audit trail."""

    def __init__(
        self,
        app: ASGIApp,
        excluded_paths: set[str] | None = None,
        excluded_methods: set[str] | None = None,
    ):
        super().__init__(app)
        self.excluded_paths = excluded_paths or {
            "/health",
            "/metrics",
            "/docs",
            "/openapi.json",
        }
        self.excluded_methods = excluded_methods or {"OPTIONS", "HEAD"}

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if request.method in self.excluded_methods or request.url.path in self.excluded_paths:
            return await call_next(request)

        start = time.perf_counter()
        response = await call_next(request)
        duration_ms = (time.perf_counter() - start) * 1000

        user = getattr(request.state, "user", None)
        username = getattr(user, "username", None) if user else None

        logger.info(
            "AUDIT: %s %s %s %d %.1fms",
            username or "anonymous",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
        )

        return response
