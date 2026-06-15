"""``weld.observability.correlation`` — correlation-id context (matrix-CI stub)."""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any

_correlation_id: ContextVar[str | None] = ContextVar("_correlation_id", default=None)


def set_correlation_id(value: str | None) -> None:
    _correlation_id.set(value)


def get_correlation_id() -> str | None:
    return _correlation_id.get()


def correlation_id_middleware(*args: Any, **kwargs: Any) -> Any:
    return None
