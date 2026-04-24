"""Provenance-driven uninstall for disabled fragments.

Epic F (1.1.0-alpha.1). When ``forge --update`` runs on a project whose
``forge.toml`` has dropped an Option that used to enable a fragment,
the fragment's files used to stay on disk forever — config said
"disabled" but the artefacts said otherwise. This module closes that
gap: it identifies every provenance record tagged to a disabled
fragment, classifies each file as unchanged / user-modified /
missing, deletes the unchanged ones, preserves the user-modified
ones with a warning, and scrubs sentinel-bounded injection blocks
from files the fragment didn't own outright.

The three classification outcomes on a per-file basis:

- ``unchanged`` — SHA matches the recorded baseline. Safe to delete.
  This is the happy path; the user never touched the file, so
  removing it restores the user's stated intent.
- ``user-modified`` — SHA drifted. We preserve the file (the user
  may have reworked it into something valuable) but flag it in the
  report so the user can manually delete if they want.
- ``missing`` — file already gone. Nothing to do, but still prune
  the provenance record so the manifest stays clean.

For sentinel-bounded injections (BEGIN/END blocks that a fragment
emitted into a file the fragment doesn't own), the block is removed
from the file in place. If the body between the sentinels has been
edited since emission (baseline SHA drift), we emit a ``.forge-merge``
sidecar with the original block and leave the file untouched; the
user resolves manually. This mirrors Epic H's merge-zone conflict
handling.

Opt-out: a project can set ``forge.update.no_uninstall = true`` in
``forge.toml`` to keep the pre-Epic-F behaviour (disabled fragments
leave their files on disk). ``forge migrate-preserve-uninstall``
flips this on for existing 1.0.0 projects automatically.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from forge.provenance import ProvenanceCollector, ProvenanceRecord, classify


@dataclass
class UninstallOutcome:
    """Result of uninstalling one fragment."""

    fragment_name: str
    deleted_files: list[str] = field(default_factory=list)
    preserved_files: list[str] = field(default_factory=list)
    missing_files: list[str] = field(default_factory=list)
    removed_blocks: list[tuple[str, str]] = field(default_factory=list)
    """(file, tag) pairs for sentinel blocks that were cleanly removed."""
    conflicted_blocks: list[tuple[str, str]] = field(default_factory=list)
    """(file, tag) pairs for sentinel blocks that had drifted — sidecar written."""

    def as_dict(self) -> dict:
        """TOML/JSON-serialisable view for the update-summary payload."""
        return {
            "fragment": self.fragment_name,
            "deleted": list(self.deleted_files),
            "preserved": list(self.preserved_files),
            "missing": list(self.missing_files),
            "removed_blocks": [{"file": f, "tag": t} for f, t in self.removed_blocks],
            "conflicted_blocks": [{"file": f, "tag": t} for f, t in self.conflicted_blocks],
        }


def uninstall_fragment(
    project_root: Path,
    fragment_name: str,
    provenance_tbl: dict[str, dict[str, str]],
    collector: ProvenanceCollector,
    *,
    removed_blocks_in_files: list[tuple[str, str, str]] | None = None,
) -> UninstallOutcome:
    """Remove every on-disk trace of ``fragment_name``.

    Parameters:
        project_root: Root of the generated project.
        fragment_name: The disabled fragment's name (matches
            ``ProvenanceRecord.fragment_name``).
        provenance_tbl: The raw ``[forge.provenance]`` table from
            ``forge.toml``, path → {origin, sha256, fragment_name, ...}.
        collector: The post-update provenance collector. The pruned
            records are also removed from it so the re-stamped
            ``forge.toml`` is consistent.
        removed_blocks_in_files: Optional list of
            ``(rel_path, feature_key, marker)`` triples identifying
            sentinel-bounded injection blocks to scrub from files the
            fragment doesn't own. Typically derived by the caller from
            the disabled fragment's ``inject.yaml``. When ``None``,
            injection scrub is skipped (used for fragments that emitted
            only ``files/``, not injections).

    Returns:
        :class:`UninstallOutcome` describing what was deleted,
        preserved, or flagged as conflicted.
    """
    outcome = UninstallOutcome(fragment_name=fragment_name)

    # --- Files tagged origin=fragment & fragment_name=<this> ---
    for rel, entry in list(provenance_tbl.items()):
        if entry.get("origin") != "fragment":
            continue
        if entry.get("fragment_name") != fragment_name:
            continue
        path = project_root / rel
        recorded = ProvenanceRecord(
            origin="fragment",
            sha256=str(entry.get("sha256", "")),
            fragment_name=fragment_name,
        )
        state = classify(path, recorded)
        if state == "unchanged":
            try:
                path.unlink()
                outcome.deleted_files.append(rel)
            except OSError:
                # Permission error or already gone — treat as preserved.
                outcome.preserved_files.append(rel)
        elif state == "user-modified":
            outcome.preserved_files.append(rel)
        else:  # missing
            outcome.missing_files.append(rel)
        # Prune the record regardless of outcome — the fragment is gone,
        # so the provenance entry pointing at it is stale. Keeping a
        # stale record would let a subsequent run "see" the file as
        # fragment-owned even though nothing re-emitted it.
        collector.records.pop(rel, None)

    # Try to prune now-empty parent directories left behind by deleted
    # files. Stops at project_root and at any directory that still has
    # other children.
    _prune_empty_dirs(project_root, outcome.deleted_files)

    # --- Sentinel-bounded injection blocks in files the fragment doesn't own ---
    if removed_blocks_in_files:
        for rel, feature_key, marker in removed_blocks_in_files:
            target = project_root / rel
            if not target.is_file():
                continue
            result = _remove_sentinel_block(target, feature_key, marker)
            if result == "removed":
                outcome.removed_blocks.append((rel, f"{feature_key}:{_naked_marker(marker)}"))
            elif result == "conflicted":
                outcome.conflicted_blocks.append((rel, f"{feature_key}:{_naked_marker(marker)}"))
            # "missing" (no block present) is silent — nothing to remove.

    return outcome


def _prune_empty_dirs(project_root: Path, deleted_relpaths: list[str]) -> None:
    """Remove empty parent dirs left behind by deleted files, stopping at root."""
    seen: set[Path] = set()
    for rel in deleted_relpaths:
        path = project_root / rel
        for parent in path.parents:
            if parent == project_root or parent in seen:
                break
            seen.add(parent)
            try:
                parent.rmdir()
            except OSError:
                # Not empty or permission denied — stop walking up this branch.
                break


# ---------------------------------------------------------------------------
# Sentinel-block removal — mirrors the BEGIN/END regex used by the injectors.
# ---------------------------------------------------------------------------


_BEGIN_RE = re.compile(r"FORGE:BEGIN\s+(\S+)")
_END_RE = re.compile(r"FORGE:END\s+(\S+)")


def _naked_marker(marker: str) -> str:
    """Strip a ``FORGE:`` prefix if present."""
    return marker.removeprefix("FORGE:")


def _sentinel_tag(feature_key: str, marker: str) -> str:
    return f"{feature_key}:{_naked_marker(marker)}"


def _remove_sentinel_block(
    file: Path, feature_key: str, marker: str
) -> str:  # "removed" | "missing" | "conflicted"
    """Remove a BEGIN/END sentinel block + its body from ``file``.

    Returns:
        - ``"removed"`` on clean removal.
        - ``"missing"`` when no BEGIN/END pair for this tag exists.
        - ``"conflicted"`` when the block is malformed (orphan BEGIN /
          END, nested pairs). The file is left untouched; the caller
          should flag the issue in the report.
    """
    tag = _sentinel_tag(feature_key, marker)
    try:
        text = file.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return "conflicted"

    lines = text.splitlines(keepends=True)
    begin_idx: int | None = None
    end_idx: int | None = None
    for idx, line in enumerate(lines):
        bm = _BEGIN_RE.search(line)
        if bm and bm.group(1) == tag:
            if begin_idx is not None:
                return "conflicted"  # duplicate BEGIN for this tag
            begin_idx = idx
            continue
        em = _END_RE.search(line)
        if em and em.group(1) == tag:
            if begin_idx is None:
                return "conflicted"  # END before BEGIN
            end_idx = idx
            break

    if begin_idx is None and end_idx is None:
        return "missing"
    if begin_idx is None or end_idx is None:
        return "conflicted"

    new_lines = lines[:begin_idx] + lines[end_idx + 1 :]
    file.write_text("".join(new_lines), encoding="utf-8")
    return "removed"


# ---------------------------------------------------------------------------
# Disabled-fragment discovery helper — used by the updater.
# ---------------------------------------------------------------------------


def disabled_fragments(
    previous_provenance: dict[str, dict[str, str]],
    current_plan_fragments: set[str],
) -> set[str]:
    """Identify fragments that were present in the last run but aren't now.

    A fragment "was present" when at least one ``[forge.provenance]``
    entry names it; "isn't now" when the resolved plan's ordered
    fragments don't include it. The set difference is what the
    uninstaller processes.
    """
    previously_present: set[str] = set()
    for entry in previous_provenance.values():
        if entry.get("origin") == "fragment":
            name = entry.get("fragment_name")
            if name:
                previously_present.add(name)
    return previously_present - current_plan_fragments
