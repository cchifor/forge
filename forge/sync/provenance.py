"""Provenance tracking for files emitted by the generator.

Every file forge writes is recorded in the project's ``forge.toml`` with
its origin, a SHA-256 of the emitted content, the originating
template/fragment + version, and a UTC timestamp. On ``forge --update``
(forward) or ``forge --harvest`` (reverse), consumers compare each
tracked file's on-disk SHA to the recorded baseline to distinguish:

  * **unchanged** — safe to re-emit or update
  * **user-modified** — preserve (or three-way-merge for ``merge``-zone
    blocks; harvest may surface as a candidate fragment patch)
  * **missing** — file was deleted post-generation

Schema version 2 (1.2.0+) records ``fragment_version`` /
``template_name`` / ``template_version`` / ``emitted_at`` per entry so
later flows can reason about the *version* of the template-or-fragment
that emitted a given file — not just its identity. Read-side back-compat
treats v1 entries (missing version fields) as "version unknown".

The provenance manifest is the substrate for both directions of the
round-trip — this module provides the recording + classification
primitives shared by forge → project (updater) and project → forge
(harvester).
"""

from __future__ import annotations

import datetime
import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

# Line-ending normalization: hash the logical content so a file written on
# Windows (CRLF) and later inspected on Linux (LF) produces the same digest.
# Mirrors Git's "text" attribute normalization for the one operation we care
# about here (integrity check), without disturbing the file on disk.


ProvenanceOrigin = Literal["base-template", "fragment", "user"]


@dataclass(frozen=True)
class ProvenanceRecord:
    """One tracked file's origin and integrity signature.

    ``origin`` distinguishes who emitted the file:
      * ``base-template`` — rendered from a Copier template
        (``services/{backend}/``, ``apps/{frontend}/``, etc.)
      * ``fragment`` — emitted by a fragment's ``files/`` or
        ``inject.yaml``
      * ``user`` — user-authored, never touched by forge

    ``fragment_name`` / ``fragment_version`` are populated when
    ``origin == "fragment"``. ``template_name`` / ``template_version``
    are populated when ``origin == "base-template"``. Both are absent
    for ``user`` entries. ``emitted_at`` is the UTC timestamp at the
    moment ``record()`` was called, in ISO-8601 form, for every entry.

    ``sha256`` is the hex digest of the content at emission time, with
    line endings normalized to LF (see :func:`sha256_of`).
    """

    origin: ProvenanceOrigin
    sha256: str
    fragment_name: str | None = None
    fragment_version: str | None = None
    template_name: str | None = None
    template_version: str | None = None
    emitted_at: str | None = None


@dataclass(frozen=True)
class MergeBlockRecord:
    """One merge-zone block's baseline + emitting fragment metadata.

    ``sha256`` is the SHA-256 of the block body (between BEGIN and END
    sentinels, exclusive). ``snippet_sha256`` is the SHA-256 of the
    ``inject.yaml`` snippet text BEFORE Jinja rendering — lets harvest
    detect whether the fragment template's snippet has drifted since
    this block was emitted. ``line_range`` is a 1-indexed
    (begin_line, end_line) tuple recording the block's position at emit
    time — a hint for error messages and the harvest content-locator,
    not authoritative (user edits invalidate the range).
    """

    sha256: str
    fragment_name: str | None = None
    fragment_version: str | None = None
    snippet_sha256: str | None = None
    line_range: tuple[int, int] | None = None


@dataclass
class ProvenanceCollector:
    """Accumulates provenance records during a generation run.

    Passed through generator + appliers to record every write.
    Paths are stored relative to the project root (as POSIX strings) so
    the manifest is portable across OSes.

    ``merge_blocks`` holds per-block baselines for merge-zone injections
    (see :mod:`forge.sync.merge`). Keyed by
    ``{rel_path}::{feature_key}:{marker}``.
    """

    project_root: Path
    records: dict[str, ProvenanceRecord] = field(default_factory=dict)
    merge_blocks: dict[str, MergeBlockRecord] = field(default_factory=dict)

    def record(
        self,
        path: Path,
        *,
        origin: ProvenanceOrigin,
        fragment_name: str | None = None,
        fragment_version: str | None = None,
        template_name: str | None = None,
        template_version: str | None = None,
    ) -> None:
        """Record provenance for a file that has just been written to disk.

        ``emitted_at`` is auto-populated with the current UTC timestamp;
        callers do not supply it. Pass ``fragment_*`` for fragment-origin
        records and ``template_*`` for base-template-origin records.
        """
        try:
            rel = path.relative_to(self.project_root)
        except ValueError:
            # Path outside the project root — skip.
            return
        key = rel.as_posix()
        if not path.is_file():
            # A fragment may declare a file that doesn't actually land (e.g. a
            # conditional template). Skip silently.
            return
        digest = sha256_of(path)
        self.records[key] = ProvenanceRecord(
            origin=origin,
            sha256=digest,
            fragment_name=fragment_name,
            fragment_version=fragment_version,
            template_name=template_name,
            template_version=template_version,
            emitted_at=_utc_now_iso(),
        )

    def drop_records_under(self, rel_prefix: str) -> None:
        """Remove records whose key is ``rel_prefix`` or lives under it.

        Used by post-generation rewrites (``strip_python_database`` in
        particular) that delete a previously-recorded subtree. Without
        pruning, the manifest retains entries pointing to files that no
        longer exist on disk — harvest and the ``forge --update`` / ``--harvest``
        flows then surface ghost candidates for those deleted paths.

        ``rel_prefix`` is a POSIX relative path. Matching is exact at the
        leaf (single-file deletion) and prefix-with-trailing-slash for
        directory deletions — so ``drop_records_under("alembic")`` removes
        ``alembic/env.py`` but leaves ``alembic.toml`` alone.
        """
        prefix_with_sep = rel_prefix.rstrip("/") + "/"
        doomed = [
            key for key in self.records if key == rel_prefix or key.startswith(prefix_with_sep)
        ]
        for key in doomed:
            del self.records[key]

    def record_merge_block(
        self,
        *,
        rel_posix_path: str,
        feature_key: str,
        marker: str,
        block_sha: str,
        fragment_name: str | None = None,
        fragment_version: str | None = None,
        snippet_sha256: str | None = None,
        line_range: tuple[int, int] | None = None,
    ) -> None:
        """Record a merge-zone baseline for three-way compare on re-apply.

        ``fragment_name`` / ``fragment_version`` identify the emitting
        fragment so harvest can route the candidate patch upstream.
        ``snippet_sha256`` lets harvest detect fragment-template drift.
        ``line_range`` is an emit-time line span (1-indexed, inclusive).
        """
        from forge.sync.merge import MergeBlockCollector  # noqa: PLC0415

        key = MergeBlockCollector.key_for(rel_posix_path, feature_key, marker)
        self.merge_blocks[key] = MergeBlockRecord(
            sha256=block_sha,
            fragment_name=fragment_name,
            fragment_version=fragment_version,
            snippet_sha256=snippet_sha256,
            line_range=line_range,
        )

    def as_dict(self) -> dict[str, dict[str, Any]]:
        """Return the collector's state in a TOML-serializable shape.

        Each entry becomes a sub-table in ``[forge.provenance]`` keyed by
        the relative path. ``None`` fields are omitted so the emitted
        TOML stays lean.
        """
        out: dict[str, dict[str, Any]] = {}
        for key, rec in sorted(self.records.items()):
            entry: dict[str, Any] = {"origin": rec.origin, "sha256": rec.sha256}
            if rec.fragment_name:
                entry["fragment_name"] = rec.fragment_name
            if rec.fragment_version:
                entry["fragment_version"] = rec.fragment_version
            if rec.template_name:
                entry["template_name"] = rec.template_name
            if rec.template_version:
                entry["template_version"] = rec.template_version
            if rec.emitted_at:
                entry["emitted_at"] = rec.emitted_at
            out[key] = entry
        return out

    def merge_blocks_as_dict(self) -> dict[str, dict[str, Any]]:
        """Return merge-block baselines in TOML-serializable shape.

        Optional fields are omitted when absent — v1 manifests (just
        ``{sha256}``) round-trip cleanly through this serializer when
        the richer metadata is unavailable.
        """
        out: dict[str, dict[str, Any]] = {}
        for key, rec in sorted(self.merge_blocks.items()):
            entry: dict[str, Any] = {"sha256": rec.sha256}
            if rec.fragment_name:
                entry["fragment_name"] = rec.fragment_name
            if rec.fragment_version:
                entry["fragment_version"] = rec.fragment_version
            if rec.snippet_sha256:
                entry["snippet_sha256"] = rec.snippet_sha256
            if rec.line_range is not None:
                entry["line_range"] = list(rec.line_range)
            out[key] = entry
        return out


def _utc_now_iso() -> str:
    """ISO-8601 UTC timestamp at second resolution.

    Format: ``YYYY-MM-DDTHH:MM:SSZ`` — matches the lexicographic-sortable
    form harvest uses to rank candidates by recency.

    Honors ``SOURCE_DATE_EPOCH`` (the reproducible-builds standard): when set
    to a valid integer, the timestamp is pinned to that epoch so two
    otherwise-identical generations produce a byte-identical ``forge.toml``
    (WS-3.3d). A missing or malformed value falls back to the wall clock.
    """
    epoch = os.environ.get("SOURCE_DATE_EPOCH")
    if epoch:
        try:
            ts = datetime.datetime.fromtimestamp(int(epoch), datetime.UTC)
        except (ValueError, OverflowError, OSError):
            ts = datetime.datetime.now(datetime.UTC)
    else:
        ts = datetime.datetime.now(datetime.UTC)
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_of(path: Path) -> str:
    """SHA-256 of a file's content with line endings normalized to LF.

    Text files written on Windows contain CRLF; the same file inspected
    under Git or on Linux contains LF. We hash the LF-normalized content
    so the integrity check isn't tripped by a platform-driven line-ending
    flip. Binary files (uncommon for forge outputs) are unaffected when
    they contain no CR bytes.
    """
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            # Strip CR before LF; leaves lone CRs (rare, legacy Mac) untouched.
            h.update(chunk.replace(b"\r\n", b"\n"))
    return h.hexdigest()


FileState = Literal["unchanged", "user-modified", "missing"]


def classify(path: Path, recorded: ProvenanceRecord) -> FileState:
    """Compare a file on disk to its recorded provenance entry.

    * ``missing`` — file no longer exists.
    * ``unchanged`` — current SHA matches the recorded SHA. The generator
      can safely re-emit without asking.
    * ``user-modified`` — SHAs differ. The caller decides how to react
      (skip, warn, three-way merge, back-up-and-replace, or surface as a
      harvest candidate).
    """
    if not path.is_file():
        return "missing"
    current = sha256_of(path)
    if current == recorded.sha256:
        return "unchanged"
    return "user-modified"
