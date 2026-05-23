"""``observability.*`` options — tracing, health, OpenTelemetry."""

from __future__ import annotations

from forge.options._registry import (
    FeatureCategory,
    Option,
    OptionType,
    register_option,
)

register_option(
    Option(
        path="observability.tracing",
        type=OptionType.BOOL,
        default=False,
        summary="Distributed tracing -- Logfire / OTel SDK / OTLP gRPC.",
        description="""\
Distributed tracing + structured logs wired out of the box. Python uses
Logfire (which exports OTLP under the hood); Node uses @opentelemetry
auto-instrumentations for HTTP / DB / Fastify spans; Rust uses
tracing-opentelemetry + OTLP gRPC. All three honour the same OTel
semantic-convention service name so your tracing backend (Jaeger,
Tempo, Honeycomb, Datadog APM, Logfire) sees one service-map across
languages.

BACKENDS: python, node, rust
REQUIRES: OTEL_EXPORTER_OTLP_ENDPOINT (or LOGFIRE_TOKEN on Python).""",
        category=FeatureCategory.OBSERVABILITY,
        enables={True: ("observability",)},
    )
)


register_option(
    Option(
        path="observability.health",
        type=OptionType.BOOL,
        default=False,
        summary="/health aggregates Postgres + Redis + Keycloak readiness.",
        description="""\
Upgrades the default /health check to a deep readiness probe that
verifies DB connectivity, Redis ping, and Keycloak health endpoint
reachability. Each dependency reports individually so an orchestrator
(Kubernetes readiness gate, load balancer) sees which specific
downstream is down rather than an opaque 503.

BACKENDS: python, node, rust
ENDPOINTS: /health (replaces the shallow default)
REQUIRES: REDIS_URL, KEYCLOAK_HEALTH_URL.""",
        category=FeatureCategory.OBSERVABILITY,
        stability="beta",
        enables={True: ("enhanced_health",)},
    )
)


register_option(
    Option(
        path="observability.error_envelope",
        type=OptionType.BOOL,
        default=True,
        summary="RFC-007 error envelope serialised via a swappable port (default on).",
        description="""\
Promotes the hand-written RFC-007 error-envelope code from base-template
hand-woven into a swappable port (``ErrorPort`` Protocol / interface /
trait). The default adapter (``DefaultErrorPort``) wraps the existing
``app.core.errors`` / ``lib/errors.ts`` / ``crate::errors`` machinery
and keeps the wire shape identical, so existing projects are unaffected
at the byte level. Plugins shipping custom envelopes implement
``ErrorPort`` themselves and register their adapter in place of
``DefaultErrorPort`` — the auth SDKs already prove the wire shape works
cross-language, so this option ships tier-1 from the start.

When ``False``, the base-template error code is stripped via the
existing strip mechanism (follow-up — until the strip lands, ``False``
is equivalent to ``True`` minus the port adapter on Python; a node /
rust strip pass is pending).

BACKENDS: python, node, rust
PORT: ``ErrorPort.serialize(exc) -> {error: {code, message, type, context, correlation_id}}``""",
        category=FeatureCategory.OBSERVABILITY,
        enables={True: ("error_port",)},
    )
)


register_option(
    Option(
        path="observability.otel",
        type=OptionType.BOOL,
        default=False,
        summary="OpenTelemetry traces + metrics via OTLP exporter (agent.run, tool.call spans).",
        description="""\
Emits ``app/core/otel.py`` wiring FastAPI + HTTPX instrumentations and an
OTLP exporter to whatever ``OTEL_EXPORTER_OTLP_ENDPOINT`` points at.
Spans of interest for agentic workloads: ``agent.run`` (per agent
invocation), ``tool.call`` (per tool invocation). Token / cost counters
from AG-UI RUN_FINISHED are attached as span attributes.

BACKENDS: python
DEPENDENCIES: opentelemetry-api / sdk / exporter-otlp / instrumentation-fastapi / instrumentation-httpx
ENV: OTEL_EXPORTER_OTLP_ENDPOINT, OTEL_SERVICE_NAME, OTEL_RESOURCE_ATTRIBUTES.""",
        category=FeatureCategory.OBSERVABILITY,
        enables={True: ("observability_otel",)},
    )
)
