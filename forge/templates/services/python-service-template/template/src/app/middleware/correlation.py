"""Correlation ID middleware.

Extracts ``X-Request-ID`` from the incoming request (or generates one),
stores it in a ContextVar, and echoes it back in the response header.
All downstream logging and outbound HTTP calls can read it via
``get_correlation_id()``.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from service.observability.correlation import (
    CORRELATION_HEADER,
    generate_correlation_id,
    set_correlation_id,
)


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        # Extract from header or generate
        correlation_id = request.headers.get(CORRELATION_HEADER) or generate_correlation_id()
        set_correlation_id(correlation_id)

        # Stash on request.state so other middleware/endpoints can read it
        request.state.correlation_id = correlation_id

        response = await call_next(request)

        # Echo back so callers can correlate
        response.headers[CORRELATION_HEADER] = correlation_id
        return response
