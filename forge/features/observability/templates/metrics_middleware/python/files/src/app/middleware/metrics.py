"""HTTP request metrics middleware.

Collects RED (Rate, Error, Duration) metrics per endpoint using
OpenTelemetry metrics API when available, falling back to a no-op
when the SDK is not installed.
"""
from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

try:
    from opentelemetry import metrics

    _meter = metrics.get_meter("http.server")
    _request_count = _meter.create_counter(
        "http.server.request.count",
        description="Total HTTP requests",
    )
    _request_duration = _meter.create_histogram(
        "http.server.request.duration",
        unit="ms",
        description="HTTP request duration in milliseconds",
    )
    _HAS_OTEL = True
except ImportError:
    _HAS_OTEL = False


class MetricsMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable[..., Any]
    ) -> Response:
        if not _HAS_OTEL:
            return await call_next(request)

        start = time.perf_counter()
        response: Response = await call_next(request)
        duration_ms = (time.perf_counter() - start) * 1000

        attrs = {
            "http.method": request.method,
            "http.route": request.url.path,
            "http.status_code": response.status_code,
        }
        _request_count.add(1, attrs)
        _request_duration.record(duration_ms, attrs)

        return response
