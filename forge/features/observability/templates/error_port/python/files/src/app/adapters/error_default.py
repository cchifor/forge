"""Default error-port adapter — RFC-007 envelope shape.

Bridges the existing ``app.core.errors`` machinery (the hand-written
mapper that already ships with the base template) to the new
:class:`app.ports.error_port.ErrorPort` Protocol. The adapter is
deliberately a thin wrapper — all the real work (MRO-walking the
mapping, surfacing structured context) lives in ``app.core.errors`` and
this adapter just composes the dict the port contract requires.

Plugins shipping custom envelopes implement :class:`ErrorPort`
themselves and register their class in place of this one (via the
project's dependency-injection container).
"""

from __future__ import annotations

from typing import Any

from app.core.errors import (
    ApplicationError,
    _context_for,
    _lookup_mapping,
)


class DefaultErrorPort:
    """The reference adapter — emits the canonical RFC-007 envelope.

    For known :class:`ApplicationError` subclasses, looks up the
    registered ``(code, status)`` pair and the structured context. For
    everything else, falls back to ``INTERNAL_ERROR`` with a redacted
    message — the central exception handler logs the real exception so
    operators can correlate via ``correlation_id``.
    """

    def serialize(self, exc: Exception) -> dict[str, Any]:
        if isinstance(exc, ApplicationError):
            code, _status = _lookup_mapping(exc)
            return {
                "error": {
                    "code": code,
                    "message": str(exc),
                    "type": type(exc).__name__,
                    "context": _context_for(exc),
                    "correlation_id": "",
                }
            }
        return {
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "An unexpected error occurred",
                "type": type(exc).__name__,
                "context": {},
                "correlation_id": "",
            }
        }
