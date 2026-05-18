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
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from time import perf_counter
from typing import Any

# -- Correlation ID (v2 Theme 10) ------------------------------------------
#
# One UUID per CLI invocation, stamped into every structured event so a
# downstream agent parsing NDJSON can stitch the events for a single
# ``forge <verb>`` call together (the host process may interleave logs from
# concurrent invocations, plugin subprocesses, etc.). Threaded via a
# ``ContextVar`` rather than a positional kwarg so existing callers don't
# need to change signatures — see ``cli/main.py`` for where it's seeded.
_correlation_id: ContextVar[str | None] = ContextVar("forge_correlation_id", default=None)


def new_correlation_id() -> str:
    """Generate, install, and return a fresh correlation ID.

    Called once at CLI entry; the returned UUID becomes the value
    ``log_event`` / ``phase_timer`` auto-attach to every record emitted
    from this thread (and any child contexts that don't explicitly reset
    the ContextVar). Subsequent calls *do* mint a fresh UUID — the
    function is the "start of a new logical invocation" hook, not a
    cache.
    """
    cid = str(uuid.uuid4())
    _correlation_id.set(cid)
    return cid


def get_correlation_id() -> str | None:
    """Return the current invocation's correlation ID, or ``None``.

    Public for tests and for plugins that want to surface the value
    outside the logging surface (e.g. embedding it in a generated
    project's ``forge.toml``).
    """
    return _correlation_id.get()


@contextmanager
def correlation_id_scope(value: str | None = None):
    """Bind a correlation ID for the duration of the ``with`` block.

    Mostly useful for tests; the CLI just calls ``new_correlation_id()``
    once at the top of ``main()`` and lets it ride for the rest of the
    process.
    """
    token = _correlation_id.set(value or str(uuid.uuid4()))
    try:
        yield _correlation_id.get()
    finally:
        _correlation_id.reset(token)


class _JsonFormatter(logging.Formatter):
    """JSON formatter emitting a flat, grep-able record per line."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
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


class _ForgeStreamHandler(logging.StreamHandler):  # type: ignore[type-arg]
    """StreamHandler tagged so ``configure_logging`` can prune only its own.

    Subclass exists purely to declare ``_forge_owned`` as a typed attribute;
    runtime behaviour is identical to ``logging.StreamHandler``.
    """

    _forge_owned: bool = True


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

    handler = _ForgeStreamHandler(stream or sys.stderr)
    if resolved_fmt == "json":
        handler.setFormatter(_JsonFormatter())
    else:
        handler.setFormatter(_TextFormatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
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

    When a correlation ID is active (set by ``new_correlation_id()`` at
    CLI entry), it's stamped automatically as ``correlation_id``. An
    explicit ``correlation_id=`` in ``fields`` wins over the ContextVar
    — useful for tests asserting deterministic IDs.
    """
    record_fields = {"event": event, **fields}
    if "correlation_id" not in record_fields:
        cid = _correlation_id.get()
        if cid is not None:
            record_fields["correlation_id"] = cid
    logger.log(
        level,
        message or event,
        extra={"_forge_event": record_fields},
    )


# -- Phase timing (Epic 4 — generation telemetry) --------------------------


@contextmanager
def phase_timer(
    logger: logging.Logger,
    event: str,
    **fields: Any,
):
    """Time a generator phase and emit a structured ``<event>`` event on exit.

    Usage::

        with phase_timer(logger, "copier.run", backend=bc.name):
            run_copier(...)

    Emits a single log record at INFO level with the duration in
    milliseconds attached as ``duration_ms``. On exception, emits the
    same event at WARNING level with ``status="failed"`` and re-raises
    — callers don't need to wrap with try/except just to get a failure
    signal in telemetry.

    The intent is observability of forge itself, not generated
    services. ``generator.generate`` wraps each phase
    (``resolver.resolve``, ``copier.run``, ``feature_injector.apply``,
    ``toolchain.install``, ``codegen.run``, ``provenance.write_toml``)
    so a future ``forge --log-json`` consumer can build a flame chart
    of generation cost without external instrumentation.
    """
    start = perf_counter()
    try:
        yield
    except BaseException:
        duration_ms = int((perf_counter() - start) * 1000)
        log_event(
            logger,
            event,
            level=logging.WARNING,
            duration_ms=duration_ms,
            status="failed",
            **fields,
        )
        raise
    else:
        duration_ms = int((perf_counter() - start) * 1000)
        log_event(
            logger,
            event,
            duration_ms=duration_ms,
            status="ok",
            **fields,
        )
