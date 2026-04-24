"""Structured logging for the forge CLI itself (P2.2).

Forge is a generator, not a runtime service, but operators running it
in CI / batch pipelines still need observability: which plugins
loaded, how long option resolution took, which fragments fell back
from AST injection to text injection, which provenance records got
written. Before this module, those events were scattered
``logger.info`` / ``logger.debug`` calls in various shapes. This
module centralizes the event vocabulary so ops teams can filter,
alert, and ship logs elsewhere.

Usage::

    from forge.logging import get_logger, configure_logging, log_event

    configure_logging()              # reads FORGE_LOG_FORMAT / FORGE_LOG_LEVEL
    logger = get_logger(__name__)

    log_event(
        logger,
        "plugin.loaded",
        plugin="my_plugin",
        options_added=3,
        duration_ms=12,
    )

Environment variables:

- ``FORGE_LOG_FORMAT``: ``text`` (default) or ``json``.
- ``FORGE_LOG_LEVEL``: ``DEBUG``, ``INFO`` (default), ``WARNING``,
  ``ERROR``. Overridden by ``--verbose`` / ``--quiet`` flags.

The ``log_event`` helper emits a stable shape regardless of format so
downstream tooling can parse it uniformly:

- text:  ``2026-04-24T10:30:00Z INFO forge.plugins plugin.loaded plugin=p1 options_added=3``
- json:  ``{"ts": "...", "level": "INFO", "logger": "forge.plugins",
           "event": "plugin.loaded", "plugin": "p1", "options_added": 3}``
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any


class _JsonFormatter(logging.Formatter):
    """JSON formatter emitting a flat, grep-able record per line."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        # Merge any structured fields attached via ``log_event``.
        for key, value in getattr(record, "_forge_event", {}).items():
            payload[key] = value
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


class _TextFormatter(logging.Formatter):
    """Human-readable formatter that still surfaces structured fields."""

    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        extras = getattr(record, "_forge_event", None)
        if extras:
            kvs = " ".join(f"{k}={_format_scalar(v)}" for k, v in extras.items())
            return f"{base} {kvs}"
        return base


def _format_scalar(value: Any) -> str:
    if isinstance(value, str) and (" " in value or "=" in value):
        return json.dumps(value)
    return str(value)


def configure_logging(
    *,
    level: str | None = None,
    fmt: str | None = None,
    stream: Any = None,
) -> None:
    """Install a single handler on the ``forge`` root logger.

    Idempotent — safe to call multiple times (subsequent calls replace
    the handler). Reads env vars when args are ``None``.
    """
    resolved_level = (level or os.getenv("FORGE_LOG_LEVEL", "INFO")).upper()
    resolved_fmt = (fmt or os.getenv("FORGE_LOG_FORMAT", "text")).lower()

    root = logging.getLogger("forge")
    # Remove forge-owned handlers; leave user-installed ones alone.
    for existing in list(root.handlers):
        if getattr(existing, "_forge_owned", False):
            root.removeHandler(existing)

    handler = logging.StreamHandler(stream or sys.stderr)
    handler._forge_owned = True  # type: ignore[attr-defined]
    if resolved_fmt == "json":
        handler.setFormatter(_JsonFormatter())
    else:
        handler.setFormatter(
            _TextFormatter("%(asctime)s %(levelname)s %(name)s %(message)s")
        )
    root.addHandler(handler)
    root.setLevel(resolved_level)
    # Let parent ``logging`` emit a warning if the level string is wrong
    # rather than silently defaulting — surfaces config typos.


def get_logger(name: str) -> logging.Logger:
    """Return a logger under the ``forge.`` namespace."""
    if not name.startswith("forge"):
        name = f"forge.{name}"
    return logging.getLogger(name)


def log_event(
    logger: logging.Logger,
    event: str,
    *,
    level: int = logging.INFO,
    message: str | None = None,
    **fields: Any,
) -> None:
    """Emit a structured event with arbitrary typed fields.

    ``event`` is a short dotted identifier (``plugin.loaded``,
    ``fragment.applied``, ``injection.fallback_text``). ``fields``
    are attached to the record and surface in JSON as top-level keys
    or in text as ``key=value`` pairs.
    """
    record_fields = {"event": event, **fields}
    logger.log(
        level,
        message or event,
        extra={"_forge_event": record_fields},
    )
