"""OpenTelemetry instruments for the SSE streamer.

A connection gauge, two counters, and a tracer, created at import via the OTel
metrics/trace API when available and falling back to no-ops otherwise (the
MeterProvider / TracerProvider is installed at startup by observability_otel;
without it these forward to the API no-op). Labels stay shallow on purpose —
tenant/user would explode cardinality without buying anything logs/traces
don't already give.
"""
from __future__ import annotations

import contextlib
from collections.abc import Iterator

try:
    from opentelemetry import metrics, trace

    _meter = metrics.get_meter("app.streaming")
    _connections_active = _meter.create_up_down_counter(
        "sse.connections.active",
        description="Open SSE stream connections.",
    )
    _events_emitted = _meter.create_counter(
        "sse.events.emitted",
        description="Domain events delivered over SSE (post-filter, on the wire).",
    )
    _subscriber_dropped = _meter.create_counter(
        "sse.subscriber.dropped",
        description="Subscribers force-closed by the bus due to backpressure (slow consumer).",
    )
    _tracer = trace.get_tracer("app.streaming")
    _HAS_OTEL = True
except ImportError:  # pragma: no cover - OTel optional
    _HAS_OTEL = False


@contextlib.contextmanager
def connect_span(stream: str) -> Iterator[None]:
    """Bracket one SSE connection: a ``stream.connect`` span + the active-
    connection gauge (incremented on enter, decremented on exit)."""
    if not _HAS_OTEL:
        yield
        return
    attrs = {"stream": stream}
    _connections_active.add(1, attrs)
    try:
        with _tracer.start_as_current_span("stream.connect", attributes=attrs):
            yield
    finally:
        _connections_active.add(-1, attrs)


def record_event_emitted(stream: str, event_type: str) -> None:
    if _HAS_OTEL:
        _events_emitted.add(1, {"stream": stream, "event.type": event_type})


def record_subscriber_dropped(stream: str) -> None:
    if _HAS_OTEL:
        _subscriber_dropped.add(1, {"stream": stream})
