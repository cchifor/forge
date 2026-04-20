"""OpenTelemetry setup — traces + metrics for the agentic request path.

Pre-wires an OTLP exporter configured from env vars so the service ships
observability-ready without the user writing any OTEL glue. Spans
of interest for agentic workloads:

    * ``agent.run``    — one span per agent invocation (POST /agent/run)
    * ``tool.call``    — one span per tool invocation
    * ``sse.chunk``    — one event per streaming chunk

Metrics emitted automatically via the FastAPI + HTTPX instrumentations:

    * ``http.server.duration`` histogram (p50/p95 latency)
    * ``http.client.duration`` histogram (downstream latency)

Env vars (standard OTEL names so Collector auto-discovers):

    OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4317
    OTEL_SERVICE_NAME=<project_name>
    OTEL_RESOURCE_ATTRIBUTES=deployment.environment=dev

Cost and token counters from AG-UI's RUN_FINISHED event are attached as
span attributes ``agent.tokens.total`` and ``agent.cost.usd`` by the
chat service's event reducer (already present when ``include_chat=true``).
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


def configure_otel(service_name: str) -> None:
    """Initialize OpenTelemetry — called once at app startup.

    Safe to call when OTEL env vars are unset; the exporter no-ops if
    no endpoint is configured.
    """
    try:
        from opentelemetry import trace  # noqa: PLC0415
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (  # noqa: PLC0415
            OTLPSpanExporter,
        )
        from opentelemetry.instrumentation.fastapi import (  # noqa: PLC0415
            FastAPIInstrumentor,  # noqa: F401 - instrumentor is applied by the caller
        )
        from opentelemetry.instrumentation.httpx import (  # noqa: PLC0415
            HTTPXClientInstrumentor,
        )
        from opentelemetry.sdk.resources import SERVICE_NAME, Resource  # noqa: PLC0415
        from opentelemetry.sdk.trace import TracerProvider  # noqa: PLC0415
        from opentelemetry.sdk.trace.export import BatchSpanProcessor  # noqa: PLC0415
    except ImportError as e:
        logger.warning("OpenTelemetry not installed, skipping setup: %s", e)
        return

    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    if not endpoint:
        logger.info("OTEL_EXPORTER_OTLP_ENDPOINT not set; spans will be discarded")
        # Still register a TracerProvider so callers creating spans don't
        # crash — the exporter simply does nothing.
        trace.set_tracer_provider(
            TracerProvider(resource=Resource.create({SERVICE_NAME: service_name}))
        )
        HTTPXClientInstrumentor().instrument()
        return

    resource = Resource.create({SERVICE_NAME: service_name})
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
    trace.set_tracer_provider(provider)

    HTTPXClientInstrumentor().instrument()
    logger.info("OpenTelemetry configured: endpoint=%s service=%s", endpoint, service_name)
