"""`.forge/lock` — serialise concurrent ``forge --update`` runs.

Epic H (1.1.0-alpha.1). Two maintainers running ``forge --update`` on
the same project at the same time used to race each other's provenance
writes; the lock file prevents that. The lock carries the owning PID +
an ISO-8601 timestamp so a crashed run leaves a recognisable stale
lock that a fresh run can reclaim.

Cross-platform PID liveness check: ``os.kill(pid, 0)`` on POSIX +
``OpenProcess`` via ctypes on Windows. Keeps the lock module stdlib-
only (no psutil dependency).

Escape hatch for read-only filesystems or the rare "I know what I'm
doing" case: ``acquire_lock(project_root, no_lock=True)`` is a no-op
context manager that skips the file machinery entirely.
"""

from __future__ import annotations

import contextlib
import json
import os
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from forge.errors import (
    PROVENANCE_UPDATE_LOCK_HELD,
    ProvenanceError,
)

LOCK_DIRNAME = ".forge"
LOCK_FILENAME = "lock"


def _lock_path(project_root: Path) -> Path:
    return project_root / LOCK_DIRNAME / LOCK_FILENAME


def _is_alive(pid: int) -> bool:
    """Return True when a process with ``pid`` is still running.

    POSIX: ``os.kill(pid, 0)`` returns cleanly for live PIDs and raises
    ``ProcessLookupError`` for stale ones.

    Windows: ``OpenProcess`` with ``PROCESS_QUERY_LIMITED_INFORMATION``
    returns a valid handle for live PIDs and 0 for stale ones.
    Use ctypes to avoid a psutil dependency.
    """
    if pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes  # noqa: PLC0415

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if handle:
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
        return False
    # POSIX
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        # PID exists but belongs to another user — still "alive" for
        # our purposes (another forge process could hold the lock).
        return True


def _read_lock(path: Path) -> dict[str, Any] | None:
    """Parse an existing lock file. Returns None on missing/corrupt."""
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return None
        return data
    except (json.JSONDecodeError, OSError):
        return None


@contextmanager
def acquire_lock(
    project_root: Path,
    *,
    no_lock: bool = False,
) -> Iterator[None]:
    """Acquire ``<project_root>/.forge/lock`` for the duration of the block.

    Writes ``{"pid": <os.getpid>, "started": "<iso>"}`` to the lock
    file on entry, removes it on exit. Reclaims stale locks (owning
    PID no longer alive) transparently.

    Raises :class:`ProvenanceError` with
    :data:`PROVENANCE_UPDATE_LOCK_HELD` when a live process already
    owns the lock.

    ``no_lock=True`` is a no-op context manager — diagnostic / read-
    only-filesystem escape hatch.
    """
    if no_lock:
        yield
        return

    lock_path = _lock_path(project_root)
    existing = _read_lock(lock_path)
    if existing is not None:
        existing_pid = int(existing.get("pid", 0))
        if _is_alive(existing_pid):
            raise ProvenanceError(
                f"Another forge --update is running on {project_root} "
                f"(pid {existing_pid}, started {existing.get('started', '?')}). "
                f"Wait for it to finish or remove {lock_path} if the other "
                f"process has crashed.",
                code=PROVENANCE_UPDATE_LOCK_HELD,
                context={
                    "project_root": str(project_root),
                    "holder_pid": existing_pid,
                    "holder_started": existing.get("started"),
                },
            )
        # Stale — previous run crashed. Reclaim transparently.

    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text(
        json.dumps(
            {
                "pid": os.getpid(),
                "started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
        ),
        encoding="utf-8",
    )
    try:
        yield
    finally:
        # Best-effort cleanup — a failure to remove is not fatal because
        # the next run will detect our PID is dead and reclaim.
        with contextlib.suppress(OSError):
            lock_path.unlink()
