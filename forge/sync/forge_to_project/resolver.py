"""Interactive walk of ``.forge-merge`` sidecars produced by ``forge --update``.

Phase 2 follow-up: the canonical "after-conflict" workflow. ``forge
--update`` (forward apply) produces ``.forge-merge`` / ``.forge-merge.bin``
sidecars for every record whose three-way decide returned ``conflict``
— the target file is preserved verbatim, the new content the fragment
wanted to emit goes next to it.

Before this verb existed, the operator had to manually:

  1. Walk every sidecar (``find . -name '*.forge-merge*'``).
  2. Diff the sidecar against the target.
  3. Pick a resolution: accept (overwrite target), reject (delete
     sidecar), or hand-merge.
  4. Re-stamp ``forge.toml`` so the resolved body becomes the new
     baseline (otherwise ``forge --verify`` keeps flagging drift and
     ``forge --update`` keeps re-emitting the same sidecar).

``forge --resolve`` automates the whole walk. The substrate (sidecar
format, the merge primitives in :mod:`forge.sync.merge`, the manifest
re-stamp helpers in :mod:`forge.sync.project_to_forge.accept`) all
exist; this module wires them into one TUI flow.

Algorithm:

  1. Discover every ``.forge-merge`` / ``.forge-merge.bin`` sidecar
     under the project root (``Path.rglob``).
  2. Sort deterministically by POSIX path so the same project yields
     the same prompt order.
  3. For each sidecar: parse the header tag, identify the target file,
     classify as block-level vs file-level vs binary-file, render a
     diff preview, prompt accept/reject/edit/skip/quit.
  4. Action handlers — accept replaces the target's content (block body
     for block-level, full file for file-level), reject just deletes
     the sidecar, edit drops the user into ``$EDITOR`` with a 3-way
     conflict scratch file, skip leaves both alone, quit terminates the
     loop and emits the remaining sidecars as skipped.
  5. On accept / edit, re-stamp ``forge.toml`` so the resolved body
     becomes the new manifest baseline.

This is non-destructive against the on-disk manifest until the operator
explicitly picks ``accept`` or ``edit``; a quit-mid-walk leaves
everything as it was, with un-resolved sidecars still on disk.

Tests monkeypatch :func:`forge.cli.interactive._ask_select` (and the
editor-runner :func:`_open_editor`) to drive the interactive flow
non-interactively.
"""

from __future__ import annotations

import contextlib
import difflib
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO, Any, Literal

from forge.fragments import MARKER_PREFIX
from forge.injectors.sentinels import _has_sentinel_block, _inject_snippet, _read_block_body
from forge.sync.manifest import read_forge_toml, write_forge_toml
from forge.sync.merge import (
    MergeBlockCollector,
    is_binary_file,
    sha256_of_file,
    sha256_of_text,
)

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


# ---------------------------------------------------------------------------
# Sidecar discovery + parsing
# ---------------------------------------------------------------------------


_HEADER_TAG_PREFIX = "# forge merge conflict — tag: "
"""Prefix of the first line of a text sidecar (see ``merge.write_sidecar``)."""

# Length of the comment-style header written by write_sidecar /
# write_file_sidecar. The header is:
#
#   # forge merge conflict — tag: ...
#   # target: ...
#   #
#   # The block below is what forge wanted to write. Your current
#   # file contents differ from both this version AND the baseline
#   # forge last wrote, so the generator cannot safely pick a
#   # resolution. Merge by hand, then delete this sidecar.
#   <blank line>
#   <payload>
#
# That's 8 leading lines (7 comment + 1 blank). Keep this in sync with
# the sidecar writers — bumped only when the header layout changes.
_HEADER_LINES = 8


@dataclass(frozen=True)
class _ParsedSidecar:
    """Materialised form of one sidecar on disk.

    Used internally — :class:`ResolveEntry` is the public shape.
    """

    path: Path
    target: Path
    rel_sidecar: str
    rel_target: str
    tag: str
    is_binary: bool
    payload_text: str = ""
    payload_bytes: bytes = b""


def _discover_sidecars(project_root: Path) -> list[Path]:
    """Return every ``.forge-merge`` / ``.forge-merge.bin`` sidecar under root.

    Sorted by POSIX path so the resolve walk is deterministic across
    platforms. Mirrors the filter in
    :func:`forge.sync.forge_to_project.updater._count_file_sidecars` —
    only the two known sidecar suffixes count, not arbitrary user files.
    """
    if not project_root.is_dir():
        return []
    out: list[Path] = []
    for path in project_root.rglob("*.forge-merge*"):
        if not path.is_file():
            continue
        if path.name.endswith(".forge-merge") or path.name.endswith(".forge-merge.bin"):
            out.append(path)
    out.sort(key=lambda p: p.as_posix())
    return out


def _target_for_sidecar(sidecar: Path) -> Path:
    """Strip the ``.forge-merge[.bin]`` suffix to recover the target path.

    The sidecar writer appends ``.forge-merge`` (text) or
    ``.forge-merge.bin`` (binary) to the target's name — see
    :func:`forge.sync.merge.write_sidecar` /
    :func:`forge.sync.merge.write_file_sidecar`. Inverse here.
    """
    name = sidecar.name
    if name.endswith(".forge-merge.bin"):
        bare = name[: -len(".forge-merge.bin")]
    elif name.endswith(".forge-merge"):
        bare = name[: -len(".forge-merge")]
    else:
        bare = name
    return sidecar.with_name(bare)


def _parse_sidecar(sidecar: Path, project_root: Path) -> _ParsedSidecar | None:
    """Read the sidecar from disk + parse its header tag.

    Returns ``None`` when the sidecar is unreadable. Binary sidecars
    (``.forge-merge.bin``) have no header — we synthesise a tag from
    the target's relative path so the classifier still has something
    to key on.
    """
    target = _target_for_sidecar(sidecar)
    rel_sidecar = _safe_relpath(sidecar, project_root)
    rel_target = _safe_relpath(target, project_root)

    if sidecar.name.endswith(".forge-merge.bin"):
        try:
            payload_bytes = sidecar.read_bytes()
        except OSError:
            return None
        return _ParsedSidecar(
            path=sidecar,
            target=target,
            rel_sidecar=rel_sidecar,
            rel_target=rel_target,
            tag=f"binary:{rel_target}",
            is_binary=True,
            payload_bytes=payload_bytes,
        )

    try:
        text = sidecar.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    tag = _extract_tag(text)
    payload = _strip_header(text)
    return _ParsedSidecar(
        path=sidecar,
        target=target,
        rel_sidecar=rel_sidecar,
        rel_target=rel_target,
        tag=tag,
        is_binary=False,
        payload_text=payload,
    )


def _extract_tag(sidecar_text: str) -> str:
    """Pull the tag out of the first header line.

    The header is written by :func:`forge.sync.merge.write_sidecar` /
    :func:`forge.sync.merge.write_file_sidecar` with a fixed first
    line:

        # forge merge conflict — tag: <tag>

    Returns an empty string when the line doesn't match — defensive,
    so a hand-edited sidecar still flows through resolution.
    """
    first_newline = sidecar_text.find("\n")
    first_line = sidecar_text[:first_newline] if first_newline != -1 else sidecar_text
    if first_line.startswith(_HEADER_TAG_PREFIX):
        return first_line[len(_HEADER_TAG_PREFIX) :].strip()
    return ""


def _strip_header(sidecar_text: str) -> str:
    """Return the payload (post-header) portion of the sidecar's content.

    The writers always emit ``_HEADER_LINES`` leading lines (7 comment
    + 1 blank separator). Anything beyond that is the payload — the
    block body for block-level, or the full file content for
    file-level.

    If the sidecar has been hand-edited and lost its header, we fall
    back to the full body — better to apply something the user can
    visually inspect than to silently lose payload.
    """
    lines = sidecar_text.splitlines(keepends=True)
    if len(lines) < _HEADER_LINES:
        return sidecar_text
    if not lines[0].startswith(_HEADER_TAG_PREFIX):
        return sidecar_text
    return "".join(lines[_HEADER_LINES:])


def _safe_relpath(p: Path, root: Path) -> str:
    """POSIX relative path; falls back to ``p.name`` when outside root.

    The sidecar walk never produces paths outside the project root in
    practice, but ``Path.relative_to`` raises ``ValueError`` for
    that case; the fallback keeps the report renderable.
    """
    try:
        return p.resolve().relative_to(root).as_posix()
    except (ValueError, OSError):
        return p.name


# ---------------------------------------------------------------------------
# Classification — block-level vs file-level
# ---------------------------------------------------------------------------


def _classify_sidecar(parsed: _ParsedSidecar) -> tuple[ResolveKind, str, str]:
    """Decide whether to apply a sidecar block-style or file-style.

    Returns ``(kind, feature_key, marker)``. For ``file`` / ``binary-file``
    the second + third elements are empty strings (those resolutions
    don't need a marker pair).

    Heuristic: the block-level tag format is ``<feature_key>:<MARKER>``
    where ``MARKER`` is the bare marker name (no ``FORGE:`` prefix).
    The file-level tag format is ``<fragment_name>:<rel/path>``, where
    the path contains a ``/`` or ``.`` — those characters wouldn't
    appear in a bare marker. We use that distinction plus the presence
    of a matching BEGIN/END sentinel pair in the target as the
    definitive signal: a tag whose pair is in the file IS block-level,
    everything else IS file-level.

    This is robust to a fragment author choosing a marker name that
    happens to look path-like — we check the target before deciding.
    """
    if parsed.is_binary:
        return "binary-file", "", ""

    # Try parsing as block-level first. The tag has the form
    # "<feature_key>:<MARKER_BARE>" and the target should carry a
    # FORGE:BEGIN ... <tag> sentinel for it.
    tag = parsed.tag
    if ":" in tag:
        feature_key, marker_bare = tag.split(":", 1)
        # Block-level markers are bare identifiers — no path
        # separators. File-level tags have a rel-path on the RHS, so
        # they contain "/" (POSIX-normalised) or "\\" (Windows) or
        # a "." (extension).
        looks_like_marker = (
            "/" not in marker_bare and "\\" not in marker_bare and "." not in marker_bare
        )
        if looks_like_marker and parsed.target.is_file():
            marker_full = f"{MARKER_PREFIX}{marker_bare}"
            if _has_sentinel_block(parsed.target, feature_key, marker_full):
                return "block", feature_key, marker_full

    # Fall through — file-level (text). Binary already returned above.
    return "file", "", ""


# ---------------------------------------------------------------------------
# Editor invocation (interactive only — tests monkeypatch)
# ---------------------------------------------------------------------------


def _open_editor(scratch_path: Path) -> int:
    """Open ``$EDITOR`` on ``scratch_path``; return the editor's exit code.

    Falls back to ``$VISUAL`` then ``notepad`` (Windows) / ``vi``
    (POSIX). Returns the subprocess return code so the caller can
    treat a non-zero exit (editor refused to run, user aborted) as a
    skip. Returns ``-1`` when no editor could be located at all — the
    caller surfaces that as an ``error`` entry.
    """
    editor = os.environ.get("EDITOR") or os.environ.get("VISUAL")
    if not editor:
        editor = "notepad" if os.name == "nt" else "vi"

    parts = editor.split()
    resolved = shutil.which(parts[0]) if parts else None
    if resolved is None:
        return -1
    cmd = [resolved, *parts[1:], str(scratch_path)]
    try:
        result = subprocess.run(cmd, check=False)
    except (OSError, subprocess.SubprocessError):
        return -1
    return result.returncode


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def resolve_sidecars(project_root: Path, *, quiet: bool = False) -> ResolveReport:
    """Walk every ``.forge-merge`` sidecar under ``project_root`` and prompt.

    Each sidecar gets a prompt (accept / reject / edit / skip / quit).
    Re-stamps ``forge.toml`` on accept and edit so the resolved content
    becomes the new baseline.

    Args:
        project_root: Project to scan. Must exist; missing project root
            raises ``FileNotFoundError`` (the CLI dispatcher maps that
            to exit 5).
        quiet: When ``True``, suppresses per-sidecar progress lines on
            stdout. Tests pass ``True``. Does NOT suppress the
            interactive prompts themselves — those go through
            questionary.

    Returns:
        A :class:`ResolveReport` carrying per-sidecar entries and
        aggregate counters.

    Raises:
        FileNotFoundError: ``project_root`` doesn't exist.
    """
    project_root = Path(project_root).resolve()
    if not project_root.exists():
        raise FileNotFoundError(f"project root does not exist: {project_root}")
    if not project_root.is_dir():
        raise FileNotFoundError(f"project root is not a directory: {project_root}")

    sidecars = _discover_sidecars(project_root)
    if not sidecars:
        return ResolveReport(project_root=project_root, entries=(), errors=())

    # Load the manifest once. None when there's no forge.toml — we
    # still walk the sidecars (the operator may want to clean them
    # up), but we won't re-stamp.
    manifest_path = project_root / "forge.toml"
    manifest_data = None
    if manifest_path.is_file():
        try:
            manifest_data = read_forge_toml(manifest_path)
        except (FileNotFoundError, ValueError):
            manifest_data = None

    # Working copies of the manifest tables. We mutate in place and
    # write back once at the end so a partial walk leaves the original
    # manifest untouched on error.
    provenance: dict[str, dict[str, Any]] = dict(manifest_data.provenance) if manifest_data else {}
    merge_blocks: dict[str, dict[str, Any]] = (
        dict(manifest_data.merge_blocks) if manifest_data else {}
    )
    any_manifest_change = False

    entries: list[ResolveEntry] = []
    counters = {"accepted": 0, "rejected": 0, "edited": 0, "skipped": 0, "error": 0}

    quit_requested = False
    for sidecar in sidecars:
        if quit_requested:
            entry = ResolveEntry(
                sidecar_path=_safe_relpath(sidecar, project_root),
                target_path=_safe_relpath(_target_for_sidecar(sidecar), project_root),
                kind="",
                action="skipped",
                reason="user quit before resolution",
            )
            entries.append(entry)
            counters["skipped"] += 1
            continue

        parsed = _parse_sidecar(sidecar, project_root)
        if parsed is None:
            entries.append(
                ResolveEntry(
                    sidecar_path=_safe_relpath(sidecar, project_root),
                    target_path="",
                    kind="",
                    action="error",
                    reason="sidecar unreadable",
                )
            )
            counters["error"] += 1
            continue

        if not parsed.target.is_file():
            entries.append(
                ResolveEntry(
                    sidecar_path=parsed.rel_sidecar,
                    target_path=parsed.rel_target,
                    kind="",
                    action="error",
                    reason="target file missing",
                )
            )
            counters["error"] += 1
            continue

        kind, feature_key, marker = _classify_sidecar(parsed)

        if not quiet:
            _render_preview(parsed, kind, feature_key, marker, sys.stdout)

        choice = _prompt_action(parsed, quiet=quiet)
        if choice == "quit":
            quit_requested = True
            entries.append(
                ResolveEntry(
                    sidecar_path=parsed.rel_sidecar,
                    target_path=parsed.rel_target,
                    kind=kind,
                    action="skipped",
                    reason="user quit before resolution",
                )
            )
            counters["skipped"] += 1
            continue

        if choice == "skip":
            entries.append(
                ResolveEntry(
                    sidecar_path=parsed.rel_sidecar,
                    target_path=parsed.rel_target,
                    kind=kind,
                    action="skipped",
                )
            )
            counters["skipped"] += 1
            continue

        if choice == "reject":
            entry, changed = _reject(
                parsed,
                kind=kind,
                feature_key=feature_key,
                marker=marker,
                merge_blocks=merge_blocks,
                provenance=provenance,
            )
            entries.append(entry)
            any_manifest_change = any_manifest_change or changed
            counters[entry.action] = counters.get(entry.action, 0) + 1
            continue

        if choice == "accept":
            entry, changed = _accept(
                parsed,
                kind=kind,
                feature_key=feature_key,
                marker=marker,
                merge_blocks=merge_blocks,
                provenance=provenance,
            )
            entries.append(entry)
            any_manifest_change = any_manifest_change or changed
            counters[entry.action] = counters.get(entry.action, 0) + 1
            continue

        # choice == "edit"
        entry, changed = _edit(
            parsed,
            kind=kind,
            feature_key=feature_key,
            marker=marker,
            merge_blocks=merge_blocks,
            provenance=provenance,
        )
        entries.append(entry)
        any_manifest_change = any_manifest_change or changed
        counters[entry.action] = counters.get(entry.action, 0) + 1

    if any_manifest_change and manifest_data is not None:
        write_forge_toml(
            manifest_path,
            version=manifest_data.version,
            project_name=manifest_data.project_name,
            templates=manifest_data.templates,
            options=manifest_data.options,
            provenance=provenance,
            merge_blocks=merge_blocks,
            template_versions=manifest_data.template_versions,
            schema_version=manifest_data.schema_version,
        )

    return ResolveReport(
        project_root=project_root,
        entries=tuple(entries),
        errors=(),
        accepted=counters["accepted"],
        rejected=counters["rejected"],
        edited=counters["edited"],
        skipped=counters["skipped"],
        error_count=counters["error"],
    )


# ---------------------------------------------------------------------------
# Prompt + preview rendering
# ---------------------------------------------------------------------------


def _prompt_action(parsed: _ParsedSidecar, *, quiet: bool) -> str:  # noqa: ARG001
    """Ask the user what to do with this sidecar.

    Returns one of ``accept`` / ``reject`` / ``edit`` / ``skip`` /
    ``quit``. Implemented as a separate function so tests can
    monkeypatch :func:`forge.cli.interactive._ask_select` — both the
    re-export on ``forge.cli`` and the module-local name resolve to
    the same callable.
    """
    # Local import keeps the resolver lazy-loaded — questionary is only
    # imported when the verb actually runs.
    from forge.cli.interactive import _ask_select  # noqa: PLC0415

    choice = _ask_select(
        f"How should forge resolve {parsed.rel_sidecar}?",
        choices=["accept", "reject", "edit", "skip", "quit"],
    )
    return choice


def _render_preview(
    parsed: _ParsedSidecar,
    kind: str,
    feature_key: str,
    marker: str,
    stream: IO[str],
) -> None:
    """Print a short diff preview for one sidecar to ``stream``.

    Block-level: scope to the BEGIN/END region. File-level (text):
    full unified diff. Binary file: just the size + sha256.
    """
    stream.write("\n")
    stream.write(f"--- sidecar: {parsed.rel_sidecar}\n")
    stream.write(f"+++ target:  {parsed.rel_target}\n")
    stream.write(f"    tag:     {parsed.tag}\n")
    stream.write(f"    kind:    {kind}\n")
    if kind == "binary-file":
        stream.write(f"    binary bytes: {len(parsed.payload_bytes)}\n")
        return

    if kind == "block":
        current = _read_block_body(parsed.target, feature_key, marker) or ""
        proposed = parsed.payload_text
    else:
        try:
            current = parsed.target.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            current = "<unreadable>"
        proposed = parsed.payload_text

    diff = difflib.unified_diff(
        current.splitlines(keepends=True),
        proposed.splitlines(keepends=True),
        fromfile="current",
        tofile="proposed",
        n=3,
    )
    for line in diff:
        stream.write(line if line.endswith("\n") else line + "\n")


# ---------------------------------------------------------------------------
# Action handlers — accept / reject / edit
# ---------------------------------------------------------------------------


def _accept(
    parsed: _ParsedSidecar,
    *,
    kind: str,
    feature_key: str,
    marker: str,
    merge_blocks: dict[str, dict[str, Any]],
    provenance: dict[str, dict[str, Any]],
) -> tuple[ResolveEntry, bool]:
    """Apply the sidecar's content to the target file and delete the sidecar.

    Returns ``(entry, manifest_changed)`` so the caller knows whether
    to mark the manifest as needing a write-back.
    """
    if kind == "block":
        ok, reason = _apply_block_body(
            parsed.target, feature_key=feature_key, marker=marker, body=parsed.payload_text
        )
        if not ok:
            return (
                ResolveEntry(
                    sidecar_path=parsed.rel_sidecar,
                    target_path=parsed.rel_target,
                    kind=kind,
                    action="error",
                    reason=reason,
                ),
                False,
            )
        new_body = _read_block_body(parsed.target, feature_key, marker) or parsed.payload_text
        changed = _restamp_block(
            merge_blocks,
            rel_target=parsed.rel_target,
            feature_key=feature_key,
            marker=marker,
            new_body=new_body,
        )
        _safe_unlink(parsed.path)
        return (
            ResolveEntry(
                sidecar_path=parsed.rel_sidecar,
                target_path=parsed.rel_target,
                kind=kind,
                action="accepted",
            ),
            changed,
        )

    if kind == "binary-file":
        try:
            parsed.target.write_bytes(parsed.payload_bytes)
        except OSError as e:
            return (
                ResolveEntry(
                    sidecar_path=parsed.rel_sidecar,
                    target_path=parsed.rel_target,
                    kind=kind,
                    action="error",
                    reason=f"write failed: {e}",
                ),
                False,
            )
        changed = _restamp_file(provenance, rel_target=parsed.rel_target, target=parsed.target)
        _safe_unlink(parsed.path)
        return (
            ResolveEntry(
                sidecar_path=parsed.rel_sidecar,
                target_path=parsed.rel_target,
                kind=kind,
                action="accepted",
            ),
            changed,
        )

    # kind == "file"
    try:
        parsed.target.write_text(parsed.payload_text, encoding="utf-8")
    except OSError as e:
        return (
            ResolveEntry(
                sidecar_path=parsed.rel_sidecar,
                target_path=parsed.rel_target,
                kind=kind,
                action="error",
                reason=f"write failed: {e}",
            ),
            False,
        )
    changed = _restamp_file(provenance, rel_target=parsed.rel_target, target=parsed.target)
    _safe_unlink(parsed.path)
    return (
        ResolveEntry(
            sidecar_path=parsed.rel_sidecar,
            target_path=parsed.rel_target,
            kind=kind,
            action="accepted",
        ),
        changed,
    )


def _reject(
    parsed: _ParsedSidecar,
    *,
    kind: str,
    feature_key: str,
    marker: str,
    merge_blocks: dict[str, dict[str, Any]],
    provenance: dict[str, dict[str, Any]],
) -> tuple[ResolveEntry, bool]:
    """Delete the sidecar; if the on-disk target differs from baseline, re-stamp.

    Rejecting the sidecar means "I want my current file/block to be the
    new baseline" — so we update the manifest to reflect the current
    on-disk content (which may already differ from the recorded
    baseline; that's the very reason the sidecar exists). The target
    file itself is left alone.
    """
    changed = False
    if kind == "block":
        current_body = _read_block_body(parsed.target, feature_key, marker)
        if current_body is not None:
            changed = _restamp_block(
                merge_blocks,
                rel_target=parsed.rel_target,
                feature_key=feature_key,
                marker=marker,
                new_body=current_body,
            )
    elif kind in ("file", "binary-file"):
        changed = _restamp_file(provenance, rel_target=parsed.rel_target, target=parsed.target)

    _safe_unlink(parsed.path)
    return (
        ResolveEntry(
            sidecar_path=parsed.rel_sidecar,
            target_path=parsed.rel_target,
            kind=kind,
            action="rejected",
        ),
        changed,
    )


def _edit(
    parsed: _ParsedSidecar,
    *,
    kind: str,
    feature_key: str,
    marker: str,
    merge_blocks: dict[str, dict[str, Any]],
    provenance: dict[str, dict[str, Any]],
) -> tuple[ResolveEntry, bool]:
    """Drop the user into ``$EDITOR`` with a 3-way conflict scratch file.

    The scratch file is laid out git-conflict style::

        <<<<<<< current
        <current body>
        =======
        <proposed body>
        >>>>>>> proposed

    After the editor exits, we validate no conflict markers remain and
    apply the edited content to the target. On failure (no editor,
    editor refused, conflict markers left) we treat as skip.
    """
    if kind == "binary-file":
        # Editing binary in a text editor is a footgun — surface an
        # error rather than producing garbage.
        return (
            ResolveEntry(
                sidecar_path=parsed.rel_sidecar,
                target_path=parsed.rel_target,
                kind=kind,
                action="error",
                reason="cannot edit binary sidecar with $EDITOR; use accept or reject",
            ),
            False,
        )

    if kind == "block":
        current = _read_block_body(parsed.target, feature_key, marker) or ""
    else:
        try:
            current = parsed.target.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            return (
                ResolveEntry(
                    sidecar_path=parsed.rel_sidecar,
                    target_path=parsed.rel_target,
                    kind=kind,
                    action="error",
                    reason=f"target unreadable: {e}",
                ),
                False,
            )

    proposed = parsed.payload_text

    scratch = parsed.target.with_suffix(parsed.target.suffix + ".forge-resolve")
    scratch_contents = (
        "<<<<<<< current\n"
        f"{_ensure_trailing_newline(current)}"
        "=======\n"
        f"{_ensure_trailing_newline(proposed)}"
        ">>>>>>> proposed\n"
    )
    try:
        scratch.write_text(scratch_contents, encoding="utf-8")
    except OSError as e:
        return (
            ResolveEntry(
                sidecar_path=parsed.rel_sidecar,
                target_path=parsed.rel_target,
                kind=kind,
                action="error",
                reason=f"scratch write failed: {e}",
            ),
            False,
        )

    before_content = scratch_contents
    rc = _open_editor(scratch)
    if rc == -1:
        _safe_unlink(scratch)
        return (
            ResolveEntry(
                sidecar_path=parsed.rel_sidecar,
                target_path=parsed.rel_target,
                kind=kind,
                action="error",
                reason="no editor available (set $EDITOR)",
            ),
            False,
        )
    if rc != 0:
        _safe_unlink(scratch)
        return (
            ResolveEntry(
                sidecar_path=parsed.rel_sidecar,
                target_path=parsed.rel_target,
                kind=kind,
                action="skipped",
                reason=f"editor exited with status {rc}",
            ),
            False,
        )

    # Read back the edited scratch file. If the user didn't actually
    # change the content (byte-identical to what we wrote) — treat as
    # skip so we don't propagate the conflict markers into the target.
    # Content comparison is more reliable than mtime on Windows (where
    # NTFS mtime is sometimes too coarse for a sub-second edit cycle).
    try:
        edited = scratch.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        _safe_unlink(scratch)
        return (
            ResolveEntry(
                sidecar_path=parsed.rel_sidecar,
                target_path=parsed.rel_target,
                kind=kind,
                action="error",
                reason=f"scratch unreadable: {e}",
            ),
            False,
        )
    if edited == before_content:
        _safe_unlink(scratch)
        return (
            ResolveEntry(
                sidecar_path=parsed.rel_sidecar,
                target_path=parsed.rel_target,
                kind=kind,
                action="skipped",
                reason="scratch file unmodified",
            ),
            False,
        )

    if "<<<<<<<" in edited or "=======" in edited or ">>>>>>>" in edited:
        _safe_unlink(scratch)
        return (
            ResolveEntry(
                sidecar_path=parsed.rel_sidecar,
                target_path=parsed.rel_target,
                kind=kind,
                action="error",
                reason="conflict markers remain in edited content",
            ),
            False,
        )

    # Apply the edited content
    if kind == "block":
        ok, reason = _apply_block_body(
            parsed.target, feature_key=feature_key, marker=marker, body=edited
        )
        if not ok:
            _safe_unlink(scratch)
            return (
                ResolveEntry(
                    sidecar_path=parsed.rel_sidecar,
                    target_path=parsed.rel_target,
                    kind=kind,
                    action="error",
                    reason=reason,
                ),
                False,
            )
        new_body = _read_block_body(parsed.target, feature_key, marker) or edited
        changed = _restamp_block(
            merge_blocks,
            rel_target=parsed.rel_target,
            feature_key=feature_key,
            marker=marker,
            new_body=new_body,
        )
    else:
        try:
            parsed.target.write_text(edited, encoding="utf-8")
        except OSError as e:
            _safe_unlink(scratch)
            return (
                ResolveEntry(
                    sidecar_path=parsed.rel_sidecar,
                    target_path=parsed.rel_target,
                    kind=kind,
                    action="error",
                    reason=f"write failed: {e}",
                ),
                False,
            )
        changed = _restamp_file(provenance, rel_target=parsed.rel_target, target=parsed.target)

    _safe_unlink(scratch)
    _safe_unlink(parsed.path)
    return (
        ResolveEntry(
            sidecar_path=parsed.rel_sidecar,
            target_path=parsed.rel_target,
            kind=kind,
            action="edited",
        ),
        changed,
    )


# ---------------------------------------------------------------------------
# Helpers — block body apply + manifest re-stamp
# ---------------------------------------------------------------------------


def _apply_block_body(
    target: Path,
    *,
    feature_key: str,
    marker: str,
    body: str,
) -> tuple[bool, str]:
    """Replace the BEGIN/END-bounded body in ``target`` with ``body``.

    Reuses :func:`forge.injectors.sentinels._inject_snippet` which handles
    the replace-in-place semantics. The body is passed as a snippet (no
    trailing newline expected by the injector — it adds them).

    Returns ``(ok, reason)`` — ``reason`` is non-empty when ``ok`` is
    False, carrying the underlying injection error.
    """
    # The injector wants the snippet WITHOUT the trailing newline (it
    # adds one per line itself via _render_block). Strip any trailing
    # newline from the body so we don't get a doubled blank line in
    # the rewritten block.
    snippet = body.rstrip("\n")
    try:
        _inject_snippet(target, feature_key, marker, snippet, position="after")
        return True, ""
    except Exception as e:  # noqa: BLE001 — surface as error entry.
        return False, f"inject failed: {e}"


def _restamp_block(
    merge_blocks: dict[str, dict[str, Any]],
    *,
    rel_target: str,
    feature_key: str,
    marker: str,
    new_body: str,
) -> bool:
    """Update the ``merge_blocks`` entry's sha256 to match the resolved body.

    Returns ``True`` when an entry was actually mutated (so the caller
    knows to write the manifest back). Returns ``False`` when no entry
    exists for this key — the resolver doesn't invent new manifest
    entries, just maintains existing ones.
    """
    key = MergeBlockCollector.key_for(rel_target, feature_key, marker)
    entry = merge_blocks.get(key)
    if entry is None:
        return False
    new_sha = sha256_of_text(new_body)
    if str(entry.get("sha256", "")) == new_sha:
        return False
    new_entry = dict(entry)
    new_entry["sha256"] = new_sha
    merge_blocks[key] = new_entry
    return True


def _restamp_file(
    provenance: dict[str, dict[str, Any]],
    *,
    rel_target: str,
    target: Path,
) -> bool:
    """Update the ``provenance`` entry's sha256 to match the resolved file.

    Returns ``True`` when an entry was actually mutated. Returns
    ``False`` when no entry exists (the file isn't tracked by the
    manifest) or the sha already matches.
    """
    entry = provenance.get(rel_target)
    if entry is None:
        return False
    if not target.is_file():
        return False
    new_sha = sha256_of_file(target)
    if str(entry.get("sha256", "")) == new_sha:
        return False
    new_entry = dict(entry)
    new_entry["sha256"] = new_sha
    provenance[rel_target] = new_entry
    return True


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


# Re-export so callers can ``from forge.sync.forge_to_project.resolver
# import is_binary_file`` without re-importing :mod:`forge.sync.merge`.
# The runtime check is a thin wrapper around the merge module's
# implementation.
__all__ = [
    "ResolveAction",
    "ResolveEntry",
    "ResolveKind",
    "ResolveReport",
    "is_binary_file",
    "resolve_sidecars",
]
