"""Error port — capability contract for RFC-007 error-envelope serialisation.

Promotes the hand-written error-handler code already shipping in the
base template into a swappable port. The base template's
``app.core.errors.domain_exception_to_response`` keeps emitting the
envelope as-is (that's the default behaviour); plugins shipping custom
envelope shapes implement :class:`ErrorPort` and register their adapter
in place of :class:`app.adapters.error_default.DefaultErrorPort`.

The port surface is intentionally tiny — one ``serialize`` method that
takes an exception and returns the JSON-ready envelope dict. HTTP
status, logging, and correlation-id propagation stay in the central
exception handlers; the port owns only the wire shape. See
``docs/rfcs/RFC-007-error-contract.md`` for the canonical envelope spec
and the cross-language port siblings:

- Node:   ``src/app/ports/error-port.ts``
- Rust:   ``src/ports/error_port.rs``

Adapters that mint custom codes (or change context shape) MUST keep the
top-level ``{"error": {...}}`` wrapper and the five required fields
(``code``, ``message``, ``type``, ``context``, ``correlation_id``);
otherwise the unified frontend client breaks. New ``code`` enum values
go through ``app.core.errors.register_domain_error`` so two features
can't silently claim the same mapping.
"""

from __future__ import annotations

from typing import Any, Protocol


class ErrorPort(Protocol):
    """Serialise a raised exception into the RFC-007 envelope.

    Implementations are pure — they MUST NOT mutate the exception or
    perform I/O. The central exception handler calls ``serialize`` once
    per request, then writes the returned dict as the response body
    with the matching HTTP status (mapped via ``register_domain_error``).

    The returned dict's shape is:

    .. code-block:: python

        {
            "error": {
                "code": "NOT_FOUND",                 # str, RFC-007 enum
                "message": "Item 'abc-123' not found",  # str, UI-safe
                "type": "NotFoundError",             # str, class name
                "context": {"entity": "Item", ...},  # dict, optional fields
                "correlation_id": "01H...",          # str, request id
            }
        }

    ``correlation_id`` SHOULD be populated by the calling handler from
    request state when available; adapters that don't have request
    context return an empty string and let the handler fill it in.
    """

    def serialize(self, exc: Exception) -> dict[str, Any]:
        """Return the RFC-007 envelope dict for ``exc``."""
