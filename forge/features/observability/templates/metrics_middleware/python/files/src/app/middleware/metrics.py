"""HTTP request metrics middleware.

Collects RED (Rate, Errors, Duration) plus in-flight (active-requests) metrics
per endpoint using the OpenTelemetry metrics API when available, falling back
to a no-op when the SDK is not installed.
"""
from __future__ import annotations

import time
from collections.abc import Awaitable, Callable

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
    _active_requests = _meter.create_up_down_counter(
        "http.server.active_requests",
        description="Number of in-flight HTTP requests",
    )
    _HAS_OTEL = True
except ImportError:
    _HAS_OTEL = False


class MetricsMiddleware(BaseHTTPMiddleware):
    #: Operational endpoints excluded from request metrics — they would
    #: dominate series cardinality / request rate without carrying business
    #: signal (health probes, scrapes, API docs).
    SKIP_PATHS = frozenset({"/health", "/metrics", "/docs", "/openapi.json"})

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if not _HAS_OTEL or request.url.path in self.SKIP_PATHS:
            return await call_next(request)

        attrs: dict[str, object] = {
            "http.method": request.method,
            "http.route": request.url.path,
        }
        _active_requests.add(1, attrs)
        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            # Record the failed request on the error path too: an unhandled
            # exception still produces a 5xx the caller sees, so it must show
            # up in the rate/error series rather than vanishing.
            attrs["http.status_code"] = 500
            _request_count.add(1, attrs)
            raise
        else:
            attrs["http.status_code"] = response.status_code
            _request_count.add(1, attrs)
            return response
        finally:
            duration_ms = (time.perf_counter() - start) * 1000
            _request_duration.record(duration_ms, attrs)
            _active_requests.add(-1, attrs)
