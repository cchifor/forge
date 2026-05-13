"""Read-only drift detection for forge-generated projects.

``forge --verify`` compares a project's on-disk state against the
``forge.toml`` manifest baselines and reports what's drifted, without
applying any changes. It's the read-only half of the bidirectional-sync
plan — the safe sibling of ``forge --update`` (forward) and the harvest
flow (reverse, Phase 4).

This module lives at ``forge/verify.py`` temporarily. Phase 3 of the
bidirectional-sync plan moves it under
``forge/sync/project_to_forge/verify.py`` as part of the module
reorganization — leave that move for the dedicated refactor PR.

Two record kinds participate:

* **File-level provenance** — every file the generator emitted, tracked
  in ``[forge.provenance]``. Compared via
  :func:`forge.provenance.classify`.
* **Merge-block baselines** — every inline injection forge made into a
  base-template file, tracked in ``[forge.merge_blocks]``. The current
  block body is read between BEGIN/END sentinels and hashed.

Drift classification:

* ``unchanged`` — current SHA matches the recorded baseline.
* ``user-modified`` — current SHA differs (file was edited, or block
  body changed).
* ``missing`` — file no longer exists on disk (for blocks: target file
  is gone).
* ``sentinel-corrupt`` — block sentinels (BEGIN/END pair) are missing
  or in inconsistent order, so the block body can't be read.

The ``worst`` field on the report rolls per-record states into a single
verdict for exit-code mapping in the CLI:

* ``"clean"`` — every tracked record is ``unchanged``.
* ``"drift"`` — at least one ``user-modified`` or ``missing`` record.
* ``"conflict"`` — at least one ``sentinel-corrupt`` record. This is
  reserved for the cases where a future ``forge --update`` *would*
  conflict; today the only producer is sentinel corruption.

  TODO(Phase 4): cross-reference each ``user-modified`` block against
  the current fragment registry so a fragment that moved upstream
  *also* trips ``conflict`` (the classic "user edited X AND fragment
  changed X" case). For now we leave that to ``forge --update`` itself
  to detect at re-apply time.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import IO, Any, Literal

from forge.forge_toml import read_forge_toml
from forge.injectors.sentinels import _read_block_body
from forge.merge import MergeBlockCollector, sha256_of_text
from forge.provenance import ProvenanceOrigin, ProvenanceRecord, classify, sha256_of

VerifyScope = Literal["all", "files", "blocks", "fragments"]
"""Which record kinds ``verify_project`` should walk.

* ``"all"`` — provenance entries + merge blocks (default).
* ``"files"`` — file-level provenance only; skip merge blocks.
* ``"blocks"`` — merge blocks only; skip file provenance.
* ``"fragments"`` — both kinds, but in principle could later filter to
  ``origin == "fragment"`` records. Treated as ``"all"`` today.
"""

VerifyFailOn = Literal["drift", "conflict", "never"]
"""Threshold for non-zero exit at the CLI layer.

* ``"drift"`` (default) — exit non-zero on any drift OR conflict.
* ``"conflict"`` — exit non-zero only on conflict; drift alone passes.
* ``"never"`` — always exit zero (use the JSON output for downstream
  branching).
"""

RecordStatus = Literal["unchanged", "user-modified", "missing", "sentinel-corrupt"]
"""Per-record classification surfaced in the verify report."""


@dataclass(frozen=True)
class FileVerifyEntry:
    """One file-provenance row in a :class:`VerifyReport`.

    ``current_sha`` is ``None`` when the file is missing on disk
    (so the consumer can distinguish "missing" from "user-modified to
    empty"). For ``unchanged`` rows it equals ``baseline_sha``.
    """

    rel_path: str
    origin: str
    status: RecordStatus
    fragment_name: str | None = None
    fragment_version: str | None = None
    template_name: str | None = None
    template_version: str | None = None
    baseline_sha: str = ""
    current_sha: str | None = None

    def as_dict(self) -> dict[str, Any]:
        """JSON-serializable form for the CLI ``--json`` envelope."""
        out: dict[str, Any] = {
            "rel_path": self.rel_path,
            "origin": self.origin,
            "status": self.status,
            "baseline_sha": self.baseline_sha,
            "current_sha": self.current_sha,
        }
        if self.fragment_name:
            out["fragment_name"] = self.fragment_name
        if self.fragment_version:
            out["fragment_version"] = self.fragment_version
        if self.template_name:
            out["template_name"] = self.template_name
        if self.template_version:
            out["template_version"] = self.template_version
        return out


@dataclass(frozen=True)
class BlockVerifyEntry:
    """One merge-block row in a :class:`VerifyReport`.

    ``key`` is the canonical ``{rel_path}::{feature_key}:{marker}``
    string stored in the manifest. ``feature_key`` and ``marker`` are
    parsed back out for convenience. ``current_sha`` is ``None`` for
    ``missing`` and ``sentinel-corrupt`` statuses (the body couldn't be
    read), and equals ``baseline_sha`` for ``unchanged``.
    """

    key: str
    rel_path: str
    feature_key: str
    marker: str
    status: RecordStatus
    fragment_name: str | None = None
    fragment_version: str | None = None
    baseline_sha: str = ""
    current_sha: str | None = None

    def as_dict(self) -> dict[str, Any]:
        """JSON-serializable form for the CLI ``--json`` envelope."""
        out: dict[str, Any] = {
            "key": self.key,
            "rel_path": self.rel_path,
            "feature_key": self.feature_key,
            "marker": self.marker,
            "status": self.status,
            "baseline_sha": self.baseline_sha,
            "current_sha": self.current_sha,
        }
        if self.fragment_name:
            out["fragment_name"] = self.fragment_name
        if self.fragment_version:
            out["fragment_version"] = self.fragment_version
        return out


VerifyWorst = Literal["clean", "drift", "conflict"]


@dataclass(frozen=True)
class VerifyReport:
    """Aggregate result of ``verify_project``.

    ``summary`` counts every record by status (across both file and
    block kinds), giving the CLI a stable shape to fold into the
    human-readable header line. ``records`` and ``merge_blocks`` carry
    the per-record details consumers need to act on drift.

    ``worst`` is the verdict used by the CLI to pick an exit code:

    * ``"clean"`` — no drift, no conflict; exit 0.
    * ``"drift"`` — user-modified or missing records present; exit 10
      (under the default ``fail_on="drift"``).
    * ``"conflict"`` — sentinel-corrupt records present; exit 11.
    """

    worst: VerifyWorst
    summary: dict[str, int]
    records: list[FileVerifyEntry] = field(default_factory=list)
    merge_blocks: list[BlockVerifyEntry] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """JSON-serializable form for the CLI ``--json`` envelope."""
        return {
            "worst": self.worst,
            "summary": dict(self.summary),
            "records": [r.as_dict() for r in self.records],
            "merge_blocks": [b.as_dict() for b in self.merge_blocks],
        }

    def render_human(self, stream: IO[str]) -> None:
        """Render a git-status-style summary to ``stream``.

        Caps the per-record sample at 20 lines so a project with
        thousands of drifted files doesn't flood the terminal — JSON
        output is the canonical channel for full inventories.
        """
        n_drift = self.summary.get("user-modified", 0) + self.summary.get("missing", 0)
        n_conflict = self.summary.get("sentinel-corrupt", 0)
        n_clean = self.summary.get("unchanged", 0)

        if self.worst == "clean":
            # Distinct file and block totals when the report mixes both.
            files = sum(1 for _ in self.records)
            blocks = sum(1 for _ in self.merge_blocks)
            stream.write(f"forge verify: clean ({files} files / {blocks} blocks unchanged)\n")
            return

        stream.write(f"forge verify: drift on {n_drift} files, {n_conflict} conflicts\n")

        # Show up to 20 drifted/conflicted records, files first then blocks.
        sample_cap = 20
        emitted = 0
        for rec in self.records:
            if emitted >= sample_cap:
                break
            if rec.status == "unchanged":
                continue
            tag = _format_file_tag(rec)
            stream.write(f"  ! {rec.rel_path}  ({tag})\n")
            emitted += 1
        for blk in self.merge_blocks:
            if emitted >= sample_cap:
                break
            if blk.status == "unchanged":
                continue
            stream.write(f"  ! {blk.key}  (block)\n")
            emitted += 1

        if (n_drift + n_conflict) > sample_cap:
            stream.write(
                f"  ... and {n_drift + n_conflict - sample_cap} more (use --json for full output)\n"
            )

        # Cleanly-unchanged tail count for context.
        if n_clean:
            stream.write(f"  ({n_clean} other records unchanged)\n")


def _format_file_tag(entry: FileVerifyEntry) -> str:
    """Compact origin tag for the human-render sample line.

    Examples: ``base-template, python-service-template@0.6.1``,
    ``fragment, middleware_cors@1.2.0``, ``fragment, cors``,
    ``base-template``.
    """
    if entry.origin == "fragment":
        if entry.fragment_name and entry.fragment_version:
            return f"fragment, {entry.fragment_name}@{entry.fragment_version}"
        if entry.fragment_name:
            return f"fragment, {entry.fragment_name}"
        return "fragment"
    if entry.origin == "base-template":
        if entry.template_name and entry.template_version:
            return f"base-template, {entry.template_name}@{entry.template_version}"
        if entry.template_name:
            return f"base-template, {entry.template_name}"
        return "base-template"
    return entry.origin


def _provenance_record_from_entry(entry: dict[str, Any]) -> ProvenanceRecord:
    """Reconstruct a :class:`ProvenanceRecord` from a manifest entry dict.

    v1 entries (schema_version=1) carry only ``origin`` and ``sha256``;
    the version + timestamp fields default to ``None``. v2 entries
    populate the full record. Missing ``origin`` defaults to
    ``base-template`` — the historical default for unmarked entries.
    """
    origin_raw = entry.get("origin", "base-template")
    # ProvenanceOrigin is a Literal; cast through str for safety.
    origin: ProvenanceOrigin = (
        "fragment"
        if origin_raw == "fragment"
        else ("user" if origin_raw == "user" else "base-template")
    )
    return ProvenanceRecord(
        origin=origin,
        sha256=str(entry.get("sha256", "")),
        fragment_name=_optional_str(entry.get("fragment_name")),
        fragment_version=_optional_str(entry.get("fragment_version")),
        template_name=_optional_str(entry.get("template_name")),
        template_version=_optional_str(entry.get("template_version")),
        emitted_at=_optional_str(entry.get("emitted_at")),
    )


def _optional_str(value: Any) -> str | None:
    """Coerce a manifest entry field to ``str | None``, dropping falsies."""
    if value is None:
        return None
    s = str(value)
    return s if s else None


def _verify_files(
    project_root: Path,
    provenance: dict[str, dict[str, Any]],
) -> list[FileVerifyEntry]:
    """Walk ``[forge.provenance]`` entries and classify each one."""
    out: list[FileVerifyEntry] = []
    for rel_path in sorted(provenance):
        entry = provenance[rel_path]
        record = _provenance_record_from_entry(entry)
        target = project_root / rel_path
        status = classify(target, record)

        # For "unchanged" the current SHA matches; "user-modified" picks
        # up the new digest so the JSON envelope tells the consumer what
        # the file now hashes to. "missing" has no current_sha.
        current_sha: str | None
        if status == "missing":
            current_sha = None
        elif status == "unchanged":
            current_sha = record.sha256
        else:
            current_sha = sha256_of(target) if target.is_file() else None

        out.append(
            FileVerifyEntry(
                rel_path=rel_path,
                origin=record.origin,
                status=status,
                fragment_name=record.fragment_name,
                fragment_version=record.fragment_version,
                template_name=record.template_name,
                template_version=record.template_version,
                baseline_sha=record.sha256,
                current_sha=current_sha,
            )
        )
    return out


def _verify_blocks(
    project_root: Path,
    merge_blocks: dict[str, dict[str, Any]],
) -> list[BlockVerifyEntry]:
    """Walk ``[forge.merge_blocks]`` entries and classify each one.

    Status decision table:

    * Target file missing on disk → ``missing``.
    * ``_read_block_body`` returns ``None`` (sentinels missing /
      corrupt / out-of-order) → ``sentinel-corrupt``.
    * Block body SHA equals baseline → ``unchanged``.
    * Otherwise → ``user-modified``.
    """
    out: list[BlockVerifyEntry] = []
    for key in sorted(merge_blocks):
        entry = merge_blocks[key]
        parsed = MergeBlockCollector.parse_key(key)
        if parsed is None:
            # Hand-edited manifest or pre-1.0.0a3 key — surface as
            # sentinel-corrupt rather than silently dropping it; the
            # operator should see *something* about the malformed key.
            out.append(
                BlockVerifyEntry(
                    key=key,
                    rel_path="",
                    feature_key="",
                    marker="",
                    status="sentinel-corrupt",
                    baseline_sha=str(entry.get("sha256", "")),
                    current_sha=None,
                )
            )
            continue
        rel_path, feature_key, marker = parsed
        target = project_root / rel_path
        baseline_sha = str(entry.get("sha256", ""))
        fragment_name = _optional_str(entry.get("fragment_name"))
        fragment_version = _optional_str(entry.get("fragment_version"))

        status: RecordStatus
        current_sha: str | None
        if not target.is_file():
            status = "missing"
            current_sha = None
        else:
            body = _read_block_body(target, feature_key, marker)
            if body is None:
                status = "sentinel-corrupt"
                current_sha = None
            else:
                current_sha = sha256_of_text(body)
                status = "unchanged" if current_sha == baseline_sha else "user-modified"

        out.append(
            BlockVerifyEntry(
                key=key,
                rel_path=rel_path,
                feature_key=feature_key,
                marker=marker,
                status=status,
                fragment_name=fragment_name,
                fragment_version=fragment_version,
                baseline_sha=baseline_sha,
                current_sha=current_sha,
            )
        )
    return out


def _summarize(
    records: list[FileVerifyEntry],
    merge_blocks: list[BlockVerifyEntry],
) -> dict[str, int]:
    """Roll per-record statuses into ``{status_name: count}``.

    The four canonical buckets always appear (with zero counts when
    empty) so JSON consumers can rely on a stable shape.
    """
    summary: dict[str, int] = {
        "unchanged": 0,
        "user-modified": 0,
        "missing": 0,
        "sentinel-corrupt": 0,
    }
    for r in records:
        summary[r.status] = summary.get(r.status, 0) + 1
    for b in merge_blocks:
        summary[b.status] = summary.get(b.status, 0) + 1
    return summary


def _compute_worst(summary: dict[str, int]) -> VerifyWorst:
    """Roll the summary into a single ``clean / drift / conflict`` verdict.

    Sentinel corruption is the only producer of ``conflict`` today —
    those records mean a future ``forge --update`` cannot safely
    re-anchor the block, so we surface the higher-severity state.
    User-modified blocks alone are *drift*; the cross-reference against
    the live fragment registry that would upgrade them to ``conflict``
    is Phase 4 work (see the module docstring TODO).
    """
    if summary.get("sentinel-corrupt", 0) > 0:
        return "conflict"
    if summary.get("user-modified", 0) > 0 or summary.get("missing", 0) > 0:
        return "drift"
    return "clean"


def verify_project(
    project_root: Path,
    *,
    scope: VerifyScope = "all",
    fail_on: VerifyFailOn = "drift",  # noqa: ARG001
) -> VerifyReport:
    """Compare ``project_root``'s on-disk state against its forge.toml manifest.

    Returns a :class:`VerifyReport` describing per-record drift. Does
    not mutate anything on disk — safe to invoke from CI gates and
    pre-commit hooks.

    Raises :class:`FileNotFoundError` if ``project_root/forge.toml`` is
    missing. Callers (the CLI dispatcher) decide whether to translate
    that into an exit code or an error envelope.

    ``fail_on`` is accepted but not consulted here — it shapes the CLI
    exit code, not the report itself. Keeping it in the public signature
    means downstream callers can pass it through without a separate
    threading dance.
    """
    manifest = project_root / "forge.toml"
    data = read_forge_toml(manifest)

    records: list[FileVerifyEntry] = []
    merge_blocks: list[BlockVerifyEntry] = []

    if scope in ("all", "files", "fragments"):
        records = _verify_files(project_root, data.provenance)
    if scope in ("all", "blocks", "fragments"):
        merge_blocks = _verify_blocks(project_root, data.merge_blocks)

    summary = _summarize(records, merge_blocks)
    worst = _compute_worst(summary)

    return VerifyReport(
        worst=worst,
        summary=summary,
        records=records,
        merge_blocks=merge_blocks,
    )
