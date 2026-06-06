"""Optional OpenTelemetry instrumentation for the event bus (vendored).

Follows the OTel messaging semantic conventions
(https://opentelemetry.io/docs/specs/semconv/messaging/) so spans line
up with whatever observability tooling consumes them.

Trace context flows over the bus through the CloudEvents ``traceparent``
extension (W3C Trace Context). Producers call :func:`inject_traceparent`
to copy the current span's traceparent into the event before
serialization; consumers' :func:`receive_span` reads that traceparent
and uses it as the parent context so the consumer's span chains under
the producer's span.

OpenTelemetry is *optional* — if the packages are missing every helper
here no-ops cleanly. Code that uses the bus never has to import OTel.
This module imports only the stdlib + (optionally) opentelemetry.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from app.events.envelope import CloudEvent

try:
    from opentelemetry import propagate, trace
    from opentelemetry.trace import SpanKind

    _OTEL_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised only when OTel is absent
    _OTEL_AVAILABLE = False
    propagate = None  # type: ignore[assignment]
    trace = None  # type: ignore[assignment]
    SpanKind = None  # type: ignore[assignment]


# Subset of the OTel messaging semantic conventions we set explicitly.
ATTR_SYSTEM = "messaging.system"
ATTR_DESTINATION = "messaging.destination.name"
ATTR_OPERATION = "messaging.operation.type"
ATTR_MESSAGE_ID = "messaging.message.id"
ATTR_MESSAGE_TYPE = "messaging.message.type"

# Identifies the v1 transport. A future bus picks its own — ``nats``,
# ``redis``, ``kafka``.
SYSTEM_POSTGRES_NOTIFY = "postgresql.listen_notify"
SYSTEM_IN_MEMORY = "memory"


def inject_traceparent(event: CloudEvent) -> CloudEvent:
    """Return a copy of ``event`` with the current span's traceparent
    set in its ``traceparent`` extension.

    No-op when OTel isn't installed or when there is no active span.
    """
    if not _OTEL_AVAILABLE:
        return event
    carrier: dict[str, str] = {}
    propagate.inject(carrier)
    tp = carrier.get("traceparent")
    if tp is None:
        return event
    return event.model_copy(update={"traceparent": tp})


@contextmanager
def publish_span(system: str, channel: str, event: CloudEvent) -> Iterator[None]:
    """PRODUCER span around a publish call. No-op without OTel."""
    if not _OTEL_AVAILABLE:
        yield
        return
    tracer = trace.get_tracer(__name__)
    with tracer.start_as_current_span(
        f"publish {channel}",
        kind=SpanKind.PRODUCER,
        attributes={
            ATTR_SYSTEM: system,
            ATTR_DESTINATION: channel,
            ATTR_OPERATION: "publish",
            ATTR_MESSAGE_ID: event.id,
            ATTR_MESSAGE_TYPE: event.type,
        },
    ):
        yield


@contextmanager
def receive_span(system: str, channel: str, event: CloudEvent) -> Iterator[None]:
    """CONSUMER span around event handling. No-op without OTel.

    Uses the event's ``traceparent`` as the parent context so the
    consumer span chains under the producer span across processes.
    """
    if not _OTEL_AVAILABLE:
        yield
        return
    tracer = trace.get_tracer(__name__)
    parent_ctx = None
    if event.traceparent:
        parent_ctx = propagate.extract({"traceparent": event.traceparent})
    with tracer.start_as_current_span(
        f"receive {channel}",
        kind=SpanKind.CONSUMER,
        attributes={
            ATTR_SYSTEM: system,
            ATTR_DESTINATION: channel,
            ATTR_OPERATION: "receive",
            ATTR_MESSAGE_ID: event.id,
            ATTR_MESSAGE_TYPE: event.type,
        },
        context=parent_ctx,
    ):
        yield
