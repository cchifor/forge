"""Context propagation helpers for the Airlock client.

When a caller is already inside a traced operation (OTel span) or
request (correlation id in a contextvar), the client forwards those IDs
to the service so the distributed trace spans end-to-end. When either is
absent, these helpers contribute nothing.

Two sources are supported:

1. W3C Trace Context via OpenTelemetry, if installed — emits both
   ``traceparent`` and ``tracestate``.
2. A ``correlation_id`` contextvar — in-process. Anyone (app code, HTTP
   middleware) can ``set`` it; every request then forwards it as
   ``X-Correlation-ID``.

There is no hard dependency on OpenTelemetry — if it isn't installed,
only the correlation-id path stays active.
"""

from __future__ import annotations

from contextvars import ContextVar

_correlation_id: ContextVar[str | None] = ContextVar("airlock_correlation_id", default=None)


def set_correlation_id(correlation_id: str | None) -> None:
    """Set the correlation id for subsequent client calls in this context."""
    _correlation_id.set(correlation_id)


def get_correlation_id() -> str | None:
    return _correlation_id.get()


def build_propagation_headers(*, extra: dict[str, str] | None = None) -> dict[str, str]:
    """Return headers that carry trace context downstream.

    Merges in ``extra`` last so explicit caller-supplied values win over
    auto-propagated ones.
    """
    headers: dict[str, str] = {}
    cid = _correlation_id.get()
    if cid:
        headers["X-Correlation-ID"] = cid
    try:
        from opentelemetry import propagate  # type: ignore[import-not-found]

        propagate.inject(headers)
    except Exception:
        # OTel not installed / no active context — silently skip.
        pass
    if extra:
        headers.update(extra)
    return headers
