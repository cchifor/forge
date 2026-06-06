"""Request correlation-id propagation.

Holds a per-request correlation id in a :class:`~contextvars.ContextVar` so any
code that runs without the request object in hand (logging filters, outbound
HTTP clients, background coroutines) can read it back via
:func:`get_correlation_id` without threading it through every call signature.

A small, framework-agnostic (stdlib only) primitive: the middleware that owns
the request lifecycle calls :func:`set_correlation_id`; everything downstream
reads. The default value is the empty string, so reads outside a request never
raise.
"""

from __future__ import annotations

import uuid
from contextvars import ContextVar

CORRELATION_HEADER = "X-Request-ID"

_correlation_id: ContextVar[str] = ContextVar("correlation_id", default="")


def get_correlation_id() -> str:
    """Return the correlation id bound to the current context (``""`` if none)."""
    return _correlation_id.get()


def set_correlation_id(value: str) -> None:
    """Bind ``value`` as the correlation id for the current context."""
    _correlation_id.set(value)


def generate_correlation_id() -> str:
    """Return a fresh, compact (16-hex-char) correlation id."""
    return uuid.uuid4().hex[:16]


__all__ = [
    "CORRELATION_HEADER",
    "generate_correlation_id",
    "get_correlation_id",
    "set_correlation_id",
]
