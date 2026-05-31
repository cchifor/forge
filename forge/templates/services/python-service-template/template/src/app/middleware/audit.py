import logging
import time
from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

logger = logging.getLogger(__name__)


def _path_matches_prefix(path: str, prefix: str) -> bool:
    """Return True if ``path`` is ``prefix`` or a child segment of it.

    Boundary-safe: ``/api/v1/health`` matches ``/api/v1/health`` and
    ``/api/v1/health/live`` but not ``/api/v1/healthz-records``. Health probes
    hit nested routes (the v1 router mounts the health router under
    ``/api/v1/health``), so an exact-equality check never skipped them.
    """
    return path == prefix or path.startswith(prefix + "/")


class AuditMiddleware(BaseHTTPMiddleware):
    """Records HTTP operations for audit trail."""

    def __init__(
        self,
        app: ASGIApp,
        excluded_paths: set[str] | None = None,
        excluded_methods: set[str] | None = None,
    ):
        super().__init__(app)
        self.excluded_paths = (
            excluded_paths
            if excluded_paths is not None
            else {
                "/health",
                "/api/v1/health",
                "/api/v1/healthz",
                "/metrics",
                "/docs",
                "/openapi.json",
                "/favicon.ico",
            }
        )
        self.excluded_methods = excluded_methods or {"OPTIONS", "HEAD"}

    def _is_excluded(self, path: str) -> bool:
        """Return True if ``path`` falls under any excluded prefix."""
        return any(_path_matches_prefix(path, p) for p in self.excluded_paths)

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if request.method in self.excluded_methods or self._is_excluded(request.url.path):
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
