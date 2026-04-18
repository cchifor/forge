"""Correlation ID middleware — ContextVar propagation layer.

Base-template ``RequestLoggingMiddleware`` already generates + stashes
``request.state.correlation_id`` and echoes the ``X-Request-ID`` response
header unconditionally, so the id exists for every request whether this
fragment is enabled or not.

This middleware sits on top and mirrors the same id into a ``ContextVar``
(``service.observability.correlation.set_correlation_id``) so asyncio
tasks spawned off the request — outbound HTTP calls, Taskiq enqueues,
downstream coroutines — can read the id via ``get_correlation_id()``
without threading it through every signature.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from app.middleware.logging import _ensure_correlation_id
from service.observability.correlation import set_correlation_id


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        correlation_id = _ensure_correlation_id(request)
        set_correlation_id(correlation_id)
        return await call_next(request)
