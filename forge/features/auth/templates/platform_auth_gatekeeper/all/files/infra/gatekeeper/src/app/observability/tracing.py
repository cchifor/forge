"""OpenTelemetry distributed tracing configuration.

Call ``configure_tracing()`` during application bootstrap to enable
automatic instrumentation of FastAPI routes, SQLAlchemy queries, and
HTTPX outbound requests.  Traces are exported via OTLP to the
configured collector (Grafana Alloy by default).

Environment variables
---------------------
OTEL_EXPORTER_OTLP_ENDPOINT
    Collector endpoint (default ``http://localhost:4318``).
OTEL_SERVICE_NAME
    Overrides the *service_name* argument.
OTEL_TRACES_ENABLED
    Set to ``false`` to disable tracing entirely.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


def configure_tracing(service_name: str) -> None:
    """Bootstrap OpenTelemetry tracing with auto-instrumentation.

    Safe to call even when OTel packages are missing — logs a warning
    and returns silently so the service can still start.
    """
    if os.getenv("OTEL_TRACES_ENABLED", "true").lower() in ("false", "0", "no"):
        logger.info("OpenTelemetry tracing disabled via OTEL_TRACES_ENABLED.")
        return

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError:
        logger.warning(
            "OpenTelemetry SDK packages not installed — tracing disabled. "
            "Install: opentelemetry-sdk opentelemetry-exporter-otlp-proto-http"
        )
        return

    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318")
    resolved_name = os.getenv("OTEL_SERVICE_NAME", service_name)

    resource = Resource.create({"service.name": resolved_name})
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{endpoint}/v1/traces"))
    )
    trace.set_tracer_provider(provider)

    # ── Auto-instrument frameworks ────────────────────────────────
    _instrument_fastapi()
    _instrument_sqlalchemy()
    _instrument_httpx()

    logger.info(
        "OpenTelemetry tracing configured → %s (endpoint: %s)", resolved_name, endpoint
    )


def _instrument_fastapi() -> None:
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor().instrument()
    except ImportError:
        logger.debug("opentelemetry-instrumentation-fastapi not installed, skipping.")


def _instrument_sqlalchemy() -> None:
    try:
        from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor  # type: ignore[import-untyped]  # ty:ignore[unresolved-import]

        SQLAlchemyInstrumentor().instrument()
    except ImportError:
        logger.debug(
            "opentelemetry-instrumentation-sqlalchemy not installed, skipping."
        )


def _instrument_httpx() -> None:
    try:
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

        HTTPXClientInstrumentor().instrument()
    except ImportError:
        logger.debug("opentelemetry-instrumentation-httpx not installed, skipping.")
