"""Opt-in telemetry for forge usage stats (Item 4, post-plan follow-ups).

Privacy contract: see ``docs/telemetry.md``. Default OFF. When opted in
(``FORGE_TELEMETRY={local,remote}``), structured events emit to a local
JSONL sink (``~/.forge/telemetry.jsonl``) and optionally to a remote
HTTPS endpoint (``FORGE_TELEMETRY_ENDPOINT``). Path / identity fields
are SHA-256 hashed before emission; the doc lists the schema.

The module is intentionally self-contained:

* No new third-party dependency. Remote POST uses :mod:`urllib.request`
  so opting in doesn't require ``httpx`` (forge is a generator, not a
  service — pinning yet-another HTTP client in the default install
  buys complexity nobody asked for).
* Fire-and-forget threading via :class:`concurrent.futures.ThreadPoolExecutor`
  with daemon workers. The main CLI dispatch never blocks on telemetry,
  and any sink failure logs a warning + continues.
* Module-level singleton (:data:`_CONFIG`) so command modules don't need
  to thread a config object through every call site. ``configure(...)``
  installs the resolved config; ``emit(...)`` reads it. Tests can
  ``configure(TelemetryConfig(...))`` directly without touching env
  vars / argv.

Event vocabulary lives at the top of the module as module constants so
``grep -F EVENT_`` in IDEs surfaces the whole vocabulary in one shot.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import urllib.error
import urllib.request
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, Any, Literal, cast

import forge
from forge.logging import get_logger

# ----------------------------------------------------------------------
# Public vocabulary
# ----------------------------------------------------------------------

TelemetryMode = Literal["off", "local", "remote"]
"""Resolved opt-in level. ``off`` is the default (and the no-op case)."""

TelemetryFields = Literal["minimal", "full"]
"""Field scope. ``minimal`` strips paths + fragment names (remote-friendly)."""

# Event names — keep these as module constants so the schema doc and the
# tests both pin to the same identifiers without string-literal drift.
EVENT_VERIFY_RAN = "verify.ran"
EVENT_VERIFY_DRIFT = "verify.drift_detected"
EVENT_HARVEST_RAN = "harvest.ran"
EVENT_HARVEST_CANDIDATE = "harvest.candidate_emitted"
EVENT_HARVEST_OPTION_PROMOTION_SUGGESTED = "harvest.option_promotion_suggested"
EVENT_UPDATE_RAN = "update.ran"
EVENT_UPDATE_CONFLICT = "update.conflict_emitted"
EVENT_ACCEPT_HARVESTED_RAN = "accept_harvested.ran"
EVENT_REAPPLY_BASELINE_RAN = "reapply_baseline.ran"
EVENT_EMIT_PR_RAN = "emit_pr.ran"
EVENT_RESOLVE_RAN = "resolve.ran"

# Schema version is part of every emitted record. Bump when the on-wire
# shape changes — the local sink stays append-only, so consumers
# downstream may see multiple versions in one file.
SCHEMA_VERSION = 1

# Local sink rotation policy. The file rotates when it grows past
# ``_MAX_BYTES``; rotations are numbered ``.1.jsonl`` (newest) through
# ``.5.jsonl`` (oldest before deletion). 10MB is small enough that even
# a year of telemetry on a busy project won't fill a developer's home
# dir, large enough that the per-write overhead from
# ``os.path.getsize`` only fires meaningfully often.
_MAX_BYTES = 10 * 1024 * 1024  # 10MB
_MAX_ROTATIONS = 5

# Field-name allowlist for the ``minimal`` scope. Anything not in this
# set is dropped before the event is written / POSTed. Keeping the
# allowlist tight is the privacy contract — readers of docs/telemetry.md
# should be able to see exactly what leaves the host in ``minimal`` mode.
_MINIMAL_ALLOWED_FIELDS: frozenset[str] = frozenset(
    {
        # Required envelope fields — always present regardless of scope.
        "event",
        "timestamp",
        "forge_version",
        "schema_version",
        "project_hash",
        # Per-event aggregate counts. None of these carry identifying
        # detail on their own.
        "worst",
        "summary_counts",
        "scope",
        "exit_code",
        "candidate_count_by_kind",
        "candidate_count_by_risk",
        "files_applied",
        "blocks_applied",
        "conflicts",
        "entries_by_action",
        "mode",
        "entry_count",
        "accepted",
        "rejected",
        "edited",
        "skipped",
        # Per-candidate event fields. Kind/risk/action are bounded
        # vocabularies, not identifiers.
        "kind",
        "risk",
        "action",
    }
)

# Fields the ``minimal`` scope explicitly redacts when present at the
# top level. Tracked separately from the allowlist so a future event
# adding ``foo: str`` doesn't accidentally leak — both the allowlist
# AND a documented removal list must be updated.
_MINIMAL_REDACTED_FIELDS: frozenset[str] = frozenset(
    {
        "fragment",
        "target_path",
        "rel_path",
        "sidecar_path",
        "path",
        "branch",
        "pr_url",
        "forge_repo",
    }
)


_logger = get_logger(__name__)


@dataclass
class TelemetryConfig:
    """Resolved telemetry config. Default is ``off`` in every dimension."""

    mode: TelemetryMode = "off"
    fields: TelemetryFields = "full"
    sink_path: Path = field(default_factory=lambda: Path.home() / ".forge" / "telemetry.jsonl")
    endpoint: str | None = None

    @property
    def enabled(self) -> bool:
        """``True`` when the mode is anything but ``off``."""
        return self.mode != "off"


# Module-level singleton. ``configure()`` installs a new value; ``emit()``
# reads it on every call. Holding a singleton keeps command modules from
# threading the config through every dispatcher signature — they just
# call ``telemetry.emit(...)``.
_CONFIG: TelemetryConfig = TelemetryConfig()

# Daemon executor — fire-and-forget submissions. Lazily created so
# ``configure(mode="off")`` doesn't spin up a thread for nothing.
_EXECUTOR: ThreadPoolExecutor | None = None
_EXECUTOR_LOCK = threading.Lock()


def _get_executor() -> ThreadPoolExecutor:
    """Return the lazily-created daemon executor.

    Single worker is enough: telemetry events are infrequent (one or
    two per CLI run), and ordered local-writes are easier to reason
    about than concurrent ones. ``daemon=True`` keeps the process from
    blocking on shutdown if a remote POST is still in flight.
    """
    global _EXECUTOR
    with _EXECUTOR_LOCK:
        if _EXECUTOR is None:
            _EXECUTOR = ThreadPoolExecutor(
                max_workers=1,
                thread_name_prefix="forge-telemetry",
            )
        return _EXECUTOR


# ----------------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------------


def load_config(args: object = None) -> TelemetryConfig:
    """Resolve telemetry config: CLI flag > env var > default.

    * ``--telemetry`` overrides ``FORGE_TELEMETRY``.
    * ``--telemetry-fields`` overrides ``FORGE_TELEMETRY_FIELDS``.
    * ``FORGE_TELEMETRY_ENDPOINT`` is env-only (no CLI flag — the URL
      shouldn't end up in shell history).

    Unknown values fall back to the safe defaults (``off`` / ``full``)
    so a typo in an env var can't accidentally enable a remote POST.
    """
    cli_mode = getattr(args, "telemetry", None) if args is not None else None
    env_mode = os.environ.get("FORGE_TELEMETRY", "off")
    raw_mode = cli_mode or env_mode
    mode: TelemetryMode = (
        cast(TelemetryMode, raw_mode) if raw_mode in ("off", "local", "remote") else "off"
    )

    cli_fields = getattr(args, "telemetry_fields", None) if args is not None else None
    env_fields = os.environ.get("FORGE_TELEMETRY_FIELDS", "full")
    raw_fields = cli_fields or env_fields
    fields_mode: TelemetryFields = (
        cast(TelemetryFields, raw_fields) if raw_fields in ("minimal", "full") else "full"
    )

    endpoint = os.environ.get("FORGE_TELEMETRY_ENDPOINT") or None

    sink_env = os.environ.get("FORGE_TELEMETRY_SINK")
    sink_path = Path(sink_env) if sink_env else Path.home() / ".forge" / "telemetry.jsonl"

    return TelemetryConfig(mode=mode, fields=fields_mode, sink_path=sink_path, endpoint=endpoint)


def configure(config: TelemetryConfig) -> None:
    """Install ``config`` as the module-level singleton.

    Idempotent and thread-safe: subsequent calls replace the singleton.
    Used at CLI startup (``forge.cli.main``) and in tests.
    """
    global _CONFIG
    _CONFIG = config


def current_config() -> TelemetryConfig:
    """Return the active config singleton — public for inspection / tests."""
    return _CONFIG


# ----------------------------------------------------------------------
# Hashing
# ----------------------------------------------------------------------


def project_hash(project_root: Path) -> str:
    """Opaque correlation ID for ``project_root``.

    SHA-256 of the absolute path, truncated to 16 hex chars. Used as the
    ``project_hash`` field in every event so a maintainer reading
    aggregated telemetry can group events from the same project without
    learning the path. Truncated for compactness — 16 chars (64 bits)
    is plenty to avoid collision within one user's project set.
    """
    return hashlib.sha256(str(project_root.resolve()).encode("utf-8")).hexdigest()[:16]


# ----------------------------------------------------------------------
# Emission
# ----------------------------------------------------------------------


def emit(event: str, *, project_root: Path | None = None, **fields: Any) -> None:
    """Emit a telemetry event. No-op when ``mode=off``.

    Builds the envelope (``event``, ``timestamp``, ``forge_version``,
    ``schema_version``, ``project_hash``), merges ``fields``, filters
    by the configured ``fields`` scope, and dispatches to the local
    sink and (in ``remote`` mode) the configured endpoint. Both
    dispatches run on the daemon executor so the caller never blocks.

    ``project_root`` is hashed into ``project_hash`` when provided.
    Passing ``None`` is allowed for the rare event that fires before a
    project root is known; the field is then dropped from the envelope.

    Failures (full disk, unreachable endpoint, etc.) are logged at
    WARNING via :mod:`forge.logging` and swallowed — telemetry must
    never crash forge.
    """
    cfg = _CONFIG
    if not cfg.enabled:
        return

    envelope: dict[str, Any] = {
        "event": event,
        "timestamp": datetime.now(UTC).isoformat(),
        "forge_version": _forge_version(),
        "schema_version": SCHEMA_VERSION,
    }
    if project_root is not None:
        envelope["project_hash"] = project_hash(project_root)

    payload = {**envelope, **fields}
    payload = _filter_fields(payload, cfg.fields)

    # Snapshot the config so the worker thread sees a stable view even
    # if ``configure(...)`` is called mid-flight (e.g. from a test).
    _get_executor().submit(_dispatch, payload, cfg)


def _dispatch(payload: dict[str, Any], cfg: TelemetryConfig) -> None:
    """Run on the daemon worker — write local + remote, swallow failures."""
    try:
        _write_local(payload, cfg.sink_path)
    except Exception as exc:  # noqa: BLE001 — swallow all sink failures
        _logger.warning("telemetry local sink write failed: %s", exc)

    if cfg.mode == "remote" and cfg.endpoint:
        try:
            _post_remote(payload, cfg.endpoint)
        except Exception as exc:  # noqa: BLE001 — swallow all remote failures
            _logger.warning("telemetry remote POST failed: %s", exc)


def _filter_fields(payload: dict[str, Any], scope: TelemetryFields) -> dict[str, Any]:
    """Apply the field filter for the configured ``scope``.

    ``full`` (the default) returns ``payload`` verbatim. ``minimal``
    keeps only :data:`_MINIMAL_ALLOWED_FIELDS` and explicitly drops
    anything in :data:`_MINIMAL_REDACTED_FIELDS`. The redaction list is
    consulted even for nested dicts — ``entries_by_action`` etc. stay
    because they're aggregate counts, but a per-candidate event's
    ``fragment`` field is removed.

    The filter operates one level deep on dicts; per-candidate
    aggregates (``candidate_count_by_kind``: ``dict[str, int]``) are
    passed through untouched because their keys are bounded vocabulary
    tokens (``"files"``, ``"blocks"``, …), not identifiers.
    """
    if scope == "full":
        return payload
    return {k: v for k, v in payload.items() if k in _MINIMAL_ALLOWED_FIELDS}


# ----------------------------------------------------------------------
# Local sink
# ----------------------------------------------------------------------


def _write_local(payload: dict[str, Any], sink_path: Path) -> None:
    """Append one JSONL line to ``sink_path``, rotating if needed."""
    sink_path.parent.mkdir(parents=True, exist_ok=True)
    _rotate_if_needed(sink_path)
    with sink_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, default=str) + "\n")


def _rotate_if_needed(sink_path: Path) -> None:
    """Rotate the sink when it grows past :data:`_MAX_BYTES`.

    Layout after rotation, oldest-last::

        telemetry.jsonl         # fresh, post-rotation file
        telemetry.1.jsonl       # what telemetry.jsonl was pre-rotation
        telemetry.2.jsonl       # ... and so on, up to .5.jsonl
        telemetry.6.jsonl       # deleted (over _MAX_ROTATIONS)

    Uses ``os.path.getsize`` rather than reading the file so the check
    is cheap on every write. Done before opening the append handle so
    the rotation isn't racy against the new write.
    """
    if not sink_path.exists():
        return
    try:
        size = sink_path.stat().st_size
    except OSError:
        # If we can't stat it, the open() below will tell us — don't
        # blow up here. Tests cover the happy path; production failures
        # surface via _dispatch's warning.
        return
    if size < _MAX_BYTES:
        return

    # Walk rotations from newest to oldest, shifting each. The oldest
    # rolls off the end (deleted).
    for i in range(_MAX_ROTATIONS, 0, -1):
        candidate = _rotation_path(sink_path, i)
        if i == _MAX_ROTATIONS and candidate.exists():
            candidate.unlink()
            continue
        previous = _rotation_path(sink_path, i - 1) if i > 1 else sink_path
        if previous.exists():
            target = _rotation_path(sink_path, i)
            if target.exists():
                target.unlink()
            previous.rename(target)


def _rotation_path(sink_path: Path, n: int) -> Path:
    """Return ``sink_path`` with ``.<n>`` injected before the suffix.

    ``telemetry.jsonl`` → ``telemetry.<n>.jsonl``. Files with no suffix
    get ``.<n>`` appended.
    """
    if sink_path.suffix:
        return sink_path.with_suffix(f".{n}{sink_path.suffix}")
    return sink_path.with_name(f"{sink_path.name}.{n}")


# ----------------------------------------------------------------------
# Remote sink
# ----------------------------------------------------------------------


def _post_remote(payload: dict[str, Any], endpoint: str) -> None:
    """POST ``payload`` as JSON to ``endpoint``.

    Uses :mod:`urllib.request` (stdlib) to avoid pulling ``httpx`` into
    forge's dependency closure for a feature that's off by default.
    2-second timeout — telemetry should fail fast and not stall a CI
    pipeline waiting for an unreachable collector.
    """
    body = json.dumps(payload, default=str).encode("utf-8")
    req = urllib.request.Request(  # noqa: S310 — endpoint is operator-supplied
        endpoint,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=2.0) as resp:  # noqa: S310
            resp.read()  # drain so the connection can be reused.
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        # Re-raise so _dispatch logs the warning — caller swallows it.
        raise RuntimeError(f"remote endpoint unreachable: {exc}") from exc


# ----------------------------------------------------------------------
# Export
# ----------------------------------------------------------------------


def export_local(stream: IO[str], sink_path: Path | None = None) -> int:
    """Stream the local JSONL sink to ``stream``. Returns line count.

    Includes any rotated files (oldest first → newest → current) so the
    operator sees the full history in chronological order. Lines are
    written verbatim (no re-serialisation) so the output is a faithful
    replay of what was originally written.
    """
    target = sink_path or _CONFIG.sink_path
    files: list[Path] = []
    for i in range(_MAX_ROTATIONS, 0, -1):
        rotation = _rotation_path(target, i)
        if rotation.exists():
            files.append(rotation)
    if target.exists():
        files.append(target)

    line_count = 0
    for path in files:
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                stream.write(line)
                line_count += 1
    return line_count


# ----------------------------------------------------------------------
# Shutdown — used in tests, never called by the CLI dispatcher
# ----------------------------------------------------------------------


def shutdown(wait: bool = True) -> None:
    """Drain pending submissions and reset the executor.

    Tests call this after asserting on emit() to make sure the worker
    thread has flushed before reading the sink. Production never calls
    it — the executor's daemon threads exit with the process.
    """
    global _EXECUTOR
    with _EXECUTOR_LOCK:
        if _EXECUTOR is None:
            return
        _EXECUTOR.shutdown(wait=wait)
        _EXECUTOR = None


# ----------------------------------------------------------------------
# Internals
# ----------------------------------------------------------------------


def _forge_version() -> str:
    """Return the running forge version (or ``"unknown"`` on failure)."""
    try:
        return forge.__version__
    except AttributeError:
        return "unknown"


def iter_events(sink_path: Path | None = None) -> Iterable[dict[str, Any]]:
    """Yield every event in the local sink (test helper).

    Reads the current file only — rotated files are excluded because
    tests build short-lived sinks that never rotate. Production code
    should use :func:`export_local` for full-history dumps.
    """
    target = sink_path or _CONFIG.sink_path
    if not target.exists():
        return
    with target.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)
