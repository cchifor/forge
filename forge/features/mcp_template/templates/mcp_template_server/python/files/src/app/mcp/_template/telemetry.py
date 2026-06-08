"""Telemetry — optional OpenTelemetry spans + Prometheus counters (vendored).

Plugin tool calls emit (when the optional deps are installed):
  * an OTel span (distributed tracing across the call chain)
  * Prometheus counters / a histogram (for a Grafana dashboard)

Both ``opentelemetry`` and ``prometheus_client`` are optional — the
module degrades to no-ops when they're absent, so the MCP server runs
with zero observability deps.

Vendored, self-contained: stdlib only (telemetry libs imported lazily,
guarded).
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager

try:
    from opentelemetry import trace  # type: ignore[import-not-found]

    _tracer = trace.get_tracer("app.mcp")
except Exception:  # pragma: no cover — optional dependency
    _tracer = None

try:
    from prometheus_client import (  # type: ignore[import-not-found]
        Counter,
        Histogram,
        make_asgi_app,
    )

    _plugin_tool_calls: Counter = Counter(
        "plugin_tool_calls_total",
        "Total MCP tool calls handled by first-party plugins.",
        ["integration_slug", "tool_name", "status"],
    )
    _plugin_tool_call_duration: Histogram = Histogram(
        "plugin_tool_call_duration_seconds",
        "Latency of MCP tool calls on first-party plugins.",
        ["integration_slug", "tool_name"],
        buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0),
    )
    _plugin_list_tools: Counter = Counter(
        "plugin_list_tools_total",
        "Total list_tools calls to first-party plugins.",
        ["integration_slug"],
    )
    _METRICS_ENABLED = True
except Exception:  # pragma: no cover — optional dependency
    _METRICS_ENABLED = False


def metrics_asgi_app():
    """ASGI app exposing Prometheus metrics. Mount at ``/metrics``.

    Returns ``None`` when prometheus_client isn't installed, so hosts can
    conditionally mount.
    """
    if not _METRICS_ENABLED:
        return None
    return make_asgi_app()


@contextmanager
def tool_call_span(
    *,
    slug: str,
    tool_name: str,
    tenant_id: str | None = None,
    integration_id: str | None = None,
) -> Iterator[object | None]:
    """Open a span + record Prometheus metrics for one tool invocation.

    ``tenant_id`` / ``integration_id`` are optional; when ``None`` they're
    recorded as empty span attributes so single-tenant hosts work too.
    """
    start = time.monotonic()
    status = "success"
    span_cm = (
        _tracer.start_as_current_span(f"plugin.{slug}.{tool_name}") if _tracer is not None else None
    )
    span = span_cm.__enter__() if span_cm is not None else None
    if span is not None:
        span.set_attribute("integration.slug", slug)
        span.set_attribute("integration.source", "plugin")
        span.set_attribute("integration.tenant_id", tenant_id or "")
        span.set_attribute("integration.id", integration_id or "")
        span.set_attribute("mcp.tool.name", tool_name)
    try:
        yield span
    except Exception:
        status = "error"
        if span_cm is not None:
            span_cm.__exit__(type(BaseException), BaseException(), None)
        raise
    else:
        if span_cm is not None:
            span_cm.__exit__(None, None, None)
    finally:
        if _METRICS_ENABLED:
            _plugin_tool_calls.labels(
                integration_slug=slug, tool_name=tool_name, status=status
            ).inc()
            _plugin_tool_call_duration.labels(integration_slug=slug, tool_name=tool_name).observe(
                time.monotonic() - start
            )


@contextmanager
def list_tools_span(
    *,
    slug: str,
    tenant_id: str | None = None,
    integration_id: str | None = None,
) -> Iterator[object | None]:
    if _METRICS_ENABLED:
        _plugin_list_tools.labels(integration_slug=slug).inc()
    if _tracer is None:
        yield None
        return
    with _tracer.start_as_current_span(f"plugin.{slug}.list_tools") as span:
        span.set_attribute("integration.slug", slug)
        span.set_attribute("integration.source", "plugin")
        span.set_attribute("integration.tenant_id", tenant_id or "")
        span.set_attribute("integration.id", integration_id or "")
        yield span
