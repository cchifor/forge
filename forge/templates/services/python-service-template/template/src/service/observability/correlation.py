"""Request correlation ID propagation.

Generates or extracts a correlation ID per request and makes it available
via a ContextVar so any code (logging, outbound HTTP, etc.) can read it
without passing it explicitly.
"""

from __future__ import annotations

import uuid
from contextvars import ContextVar

CORRELATION_HEADER = "X-Request-ID"

_correlation_id: ContextVar[str] = ContextVar("correlation_id", default="")


def get_correlation_id() -> str:
    return _correlation_id.get()


def set_correlation_id(value: str) -> None:
    _correlation_id.set(value)


def generate_correlation_id() -> str:
    return uuid.uuid4().hex[:16]
