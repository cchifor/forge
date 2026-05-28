"""Shared types + helpers for the resolver package.

Split out from the original ``resolver.py`` god module — see
:mod:`forge.sync.forge_to_project.resolver` for the public surface.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO, Any, Literal

# Action vocabulary surfaced in :class:`ResolveEntry`.
#
# * ``accepted``  — sidecar content applied to target; manifest re-stamped.
# * ``rejected``  — sidecar deleted; target preserved; manifest re-stamped
#                   to the on-disk body (which may differ from baseline —
#                   the user's edit becomes the new baseline).
# * ``edited``    — user hand-merged via ``$EDITOR``; resolved content
#                   applied to target; manifest re-stamped.
# * ``skipped``   — sidecar + target both untouched; loop continues.
# * ``error``     — couldn't process this sidecar (missing target,
#                   editor unavailable, sentinel corruption, etc.); the
#                   sidecar stays on disk.
ResolveAction = Literal["accepted", "rejected", "edited", "skipped", "error"]
"""Per-entry action surfaced in :class:`ResolveEntry`."""

# Sidecar kind. ``block`` is an inline-block sidecar (the conflict was
# inside a BEGIN/END sentinel-bounded region); ``file`` is a full-file
# sidecar (text); ``binary-file`` is the bytes-level twin (no header,
# just raw payload — written as ``.forge-merge.bin``).
ResolveKind = Literal["block", "file", "binary-file"]
"""Per-entry sidecar classification."""


@dataclass(frozen=True)
class ResolveEntry:
    """One sidecar's disposition after the resolve walk.

    Attributes:
        sidecar_path: POSIX-relative path of the sidecar file.
        target_path: POSIX-relative path of the target file the sidecar
            was meant to update.
        kind: Classification — ``block`` / ``file`` / ``binary-file``.
            Block-level resolution mutates only the BEGIN/END-bounded
            region; file-level resolution overwrites the whole file.
        action: One of :data:`ResolveAction`. ``accepted`` / ``edited``
            are the success cases; ``rejected`` deletes the sidecar
            without applying it; ``skipped`` leaves the sidecar on disk
            for a later run; ``error`` records a per-sidecar failure.
        reason: Free-form note. For ``error`` rows carries the failure
            reason; for ``skipped`` rows may carry a hint ("user quit
            before resolution"); empty for the happy cases.
    """

    sidecar_path: str
    target_path: str
    kind: str
    action: str
    reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        """JSON-serializable form for the CLI ``--json`` envelope."""
        out: dict[str, Any] = {
            "sidecar_path": self.sidecar_path,
            "target_path": self.target_path,
            "kind": self.kind,
            "action": self.action,
        }
        if self.reason:
            out["reason"] = self.reason
        return out


@dataclass(frozen=True)
class ResolveReport:
    """Aggregate result of :func:`resolve_sidecars`.

    Attributes:
        project_root: Absolute path of the project the sidecars were
            walked under.
        entries: Per-sidecar dispositions, in walk order. Empty when no
            sidecars were found.
        errors: Project-level errors (missing project root, unreadable
            ``forge.toml``). Per-sidecar errors live in ``entries``.
        accepted, rejected, edited, skipped, error_count: Per-action
            counters. Used by the human-renderer header and the JSON
            envelope.
    """

    project_root: Path
    entries: tuple[ResolveEntry, ...] = field(default_factory=tuple)
    errors: tuple[str, ...] = field(default_factory=tuple)
    accepted: int = 0
    rejected: int = 0
    edited: int = 0
    skipped: int = 0
    error_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        """JSON-serializable form for the CLI ``--json`` envelope."""
        return {
            "project_root": str(self.project_root),
            "accepted": self.accepted,
            "rejected": self.rejected,
            "edited": self.edited,
            "skipped": self.skipped,
            "errored": self.error_count,
            "entries": [e.as_dict() for e in self.entries],
            "errors": list(self.errors),
        }

    def render_human(self, stream: IO[str]) -> None:
        """Render a short summary + per-sidecar sample to ``stream``.

        Caps the per-record sample at 20 lines so a project with
        thousands of sidecars doesn't flood the terminal — JSON is the
        canonical channel for full inventories.
        """
        if self.errors:
            stream.write(f"forge resolve: error ({len(self.errors)})\n")
            for err in self.errors[:20]:
                stream.write(f"  ! {err}\n")
            return

        if not self.entries:
            stream.write(f"forge resolve: no .forge-merge sidecars under {self.project_root}\n")
            return

        stream.write(
            f"forge resolve: accepted={self.accepted} rejected={self.rejected} "
            f"edited={self.edited} skipped={self.skipped} errored={self.error_count}\n"
        )

        sample_cap = 20
        emitted = 0
        for entry in self.entries:
            if emitted >= sample_cap:
                break
            marker = {
                "accepted": "+",
                "edited": "+",
                "rejected": "-",
                "skipped": " ",
                "error": "!",
            }.get(entry.action, " ")
            note = f"  ({entry.reason})" if entry.reason else ""
            stream.write(f"  {marker} {entry.sidecar_path} [{entry.action}]{note}\n")
            emitted += 1
        remaining = len(self.entries) - emitted
        if remaining > 0:
            stream.write(f"  ... and {remaining} more (use --json for full output)\n")


def _resolve_editor_cmd() -> list[str] | None:
    """Resolve the editor command prefix from ``$EDITOR``/``$VISUAL``.

    Falls back to ``notepad`` (Windows) / ``vi`` (POSIX). Returns the
    resolved argv prefix (editor binary absolute path + any flags), or
    ``None`` when no editor binary can be located on PATH.
    """
    editor = os.environ.get("EDITOR") or os.environ.get("VISUAL")
    if not editor:
        editor = "notepad" if os.name == "nt" else "vi"

    parts = editor.split()
    resolved = shutil.which(parts[0]) if parts else None
    if resolved is None:
        return None
    return [resolved, *parts[1:]]


def _open_editor(
    scratch_path: Path,
    *,
    resolve: Callable[[], list[str] | None] | None = None,
    run: Callable[..., subprocess.CompletedProcess[Any]] | None = None,
) -> int:
    """Open the configured editor on ``scratch_path``; return its exit code.

    ``resolve`` and ``run`` are injectable seams for testing; production
    callers use the defaults (``$EDITOR``/``$VISUAL`` resolution and
    ``subprocess.run``). ``run`` is looked up at call time so a
    module-level ``subprocess.run`` monkeypatch still takes effect.

    Returns the editor's return code, or ``-1`` when no editor could be
    located at all — the caller surfaces that as an ``error`` entry.
    """
    resolve = resolve or _resolve_editor_cmd
    cmd_prefix = resolve()
    if cmd_prefix is None:
        return -1
    cmd = [*cmd_prefix, str(scratch_path)]
    runner = run if run is not None else subprocess.run
    try:
        result = runner(cmd, check=False)
    except (OSError, subprocess.SubprocessError):
        return -1
    return result.returncode


def _safe_unlink(path: Path) -> None:
    """Delete ``path`` if it exists; swallow OSError.

    Sidecars can be missing if a parallel process beat us to them, or
    on Windows if the file is locked — neither is a fatal error for
    the resolve walk.
    """
    with contextlib.suppress(OSError):
        path.unlink(missing_ok=True)


def _ensure_trailing_newline(text: str) -> str:
    """Append ``\\n`` to ``text`` when it doesn't already end with one.

    Keeps the 3-way scratch file's section separators on their own
    lines even when the upstream body is newline-less.
    """
    if text and not text.endswith("\n"):
        return text + "\n"
    return text
