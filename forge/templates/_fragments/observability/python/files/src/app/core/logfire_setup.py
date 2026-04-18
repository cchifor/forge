"""Logfire / OpenTelemetry configuration.

Instruments FastAPI, asyncpg, and the stdlib logger. No-ops cleanly when the
LOGFIRE_TOKEN env var is unset (Logfire's own ``send_to_logfire="if-token-present"``
handles that). Safe to call from multiple places; Logfire dedupes.

Call :func:`setup_observability` once at application startup, before the first
route is served.
"""

from __future__ import annotations

import os
from typing import Any


def setup_observability(app: Any | None = None, service_name: str | None = None) -> None:
    """Configure Logfire and wire up auto-instrumentation.

    Lazy-imports ``logfire`` so a generated project without the dependency
    installed can still import this module without error. Missing the
    dependency logs a warning but does not abort startup.
    """
    try:
        import logfire
    except ImportError:
        import logging

        logging.getLogger(__name__).warning(
            "observability feature enabled but `logfire` is not installed; "
            "run `uv sync` to pull it in",
        )
        return

    logfire.configure(
        token=os.environ.get("LOGFIRE_TOKEN"),
        service_name=service_name or os.environ.get("LOGFIRE_SERVICE_NAME", "forge-service"),
        send_to_logfire="if-token-present",
    )

    # Instrumentations. Each is best-effort — an older logfire version may
    # lack one and the others should still install.
    _try(lambda: logfire.instrument_pydantic_ai() if hasattr(logfire, "instrument_pydantic_ai") else None)
    _try(lambda: logfire.instrument_asyncpg() if hasattr(logfire, "instrument_asyncpg") else None)
    _try(lambda: logfire.instrument_sqlalchemy() if hasattr(logfire, "instrument_sqlalchemy") else None)
    if app is not None and hasattr(logfire, "instrument_fastapi"):
        _try(lambda: logfire.instrument_fastapi(app))


def _try(fn) -> None:
    import logging

    try:
        fn()
    except Exception as e:  # noqa: BLE001
        logging.getLogger(__name__).debug("logfire instrumentation skipped: %s", e)
