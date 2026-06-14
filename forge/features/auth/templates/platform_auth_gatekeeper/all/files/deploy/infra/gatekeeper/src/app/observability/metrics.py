"""OpenTelemetry metrics middleware for FastAPI.

Collects standard RED (Rate, Errors, Duration) metrics and exports them
via OTLP to Grafana Alloy.  Uses the OTel Metrics SDK instead of
``prometheus_client`` for a unified telemetry pipeline.

Environment variables
---------------------
OTEL_METRICS_ENABLED
    Set to ``false`` to disable metrics entirely.
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)

# Lazy-initialized meters (set by configure_metrics)
_request_duration = None
_request_count = None
_active_requests = None
_initialized = False


def configure_metrics(service_name: str) -> None:
    """Initialize OTel metrics instruments.

    Safe to call even when OTel is not installed — logs a warning and
    returns silently.
    """
    global _request_duration, _request_count, _active_requests, _initialized

    if os.getenv("OTEL_METRICS_ENABLED", "true").lower() in ("false", "0", "no"):
        logger.info("OpenTelemetry metrics disabled via OTEL_METRICS_ENABLED.")
        return

    try:
        from opentelemetry import metrics
        from opentelemetry.exporter.otlp.proto.http.metric_exporter import (
            OTLPMetricExporter,
        )
        from opentelemetry.sdk.metrics import MeterProvider
        from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
        from opentelemetry.sdk.resources import Resource
    except ImportError:
        logger.warning(
            "OpenTelemetry metrics packages not installed — metrics disabled. "
            "Install: opentelemetry-sdk opentelemetry-exporter-otlp-proto-http"
        )
        return

    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318")
    resolved_name = os.getenv("OTEL_SERVICE_NAME", service_name)

    resource = Resource.create({"service.name": resolved_name})
    reader = PeriodicExportingMetricReader(
        OTLPMetricExporter(endpoint=f"{endpoint}/v1/metrics"),
        export_interval_millis=15_000,
    )
    provider = MeterProvider(resource=resource, metric_readers=[reader])
    metrics.set_meter_provider(provider)

    meter = metrics.get_meter(resolved_name)
    _request_duration = meter.create_histogram(
        name="http.server.request.duration",
        description="Duration of HTTP server requests",
        unit="s",
    )
    _request_count = meter.create_counter(
        name="http.server.request.count",
        description="Total HTTP server requests",
    )
    _active_requests = meter.create_up_down_counter(
        name="http.server.active_requests",
        description="Number of in-flight HTTP requests",
    )
    _initialized = True
    logger.info("OpenTelemetry metrics configured for %s", resolved_name)


class MetricsMiddleware(BaseHTTPMiddleware):
    """Collects HTTP request metrics via OpenTelemetry."""

    SKIP_PATHS = frozenset({"/health", "/metrics", "/docs", "/openapi.json"})

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if not _initialized or request.url.path in self.SKIP_PATHS:
            return await call_next(request)

        attrs = {
            "http.method": request.method,
            "http.route": request.url.path,
        }

        _active_requests.add(1, attrs)
        start = time.perf_counter()

        try:
            response = await call_next(request)
        except Exception:
            attrs["http.status_code"] = 500
            _request_count.add(1, attrs)
            raise
        else:
            attrs["http.status_code"] = response.status_code
            _request_count.add(1, attrs)
            return response
        finally:
            duration = time.perf_counter() - start
            _request_duration.record(duration, attrs)
            _active_requests.add(-1, attrs)
