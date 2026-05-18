"""Action handlers — accept / reject / edit + manifest re-stamp helpers.

Split out from the original ``resolver.py`` god module — see
:mod:`forge.sync.forge_to_project.resolver` for the public surface.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from forge.injectors.sentinels import _inject_snippet, _read_block_body
from forge.sync.forge_to_project.resolver._shared import (
    ResolveEntry,
    _ensure_trailing_newline,
    _open_editor,
    _safe_unlink,
)
from forge.sync.forge_to_project.resolver._sidecar_parser import _ParsedSidecar
from forge.sync.merge import (
    MergeBlockCollector,
    sha256_of_file,
    sha256_of_text,
)


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
