"""Provenance tracking for files emitted by the generator.

Every file forge writes is recorded in the project's ``forge.toml`` with
its origin, a SHA-256 of the emitted content, and (for fragment-authored
files) the fragment name + version. On ``forge --update``, the updater
compares each tracked file's on-disk SHA to the recorded baseline to
distinguish:

  * **unchanged** — safe to re-emit or update
  * **user-modified** — preserve (or, with three-zone merge in 2.2,
    three-way-merge against the baseline)
  * **fragment-modified-since-last-update** — a fragment upgrade wants to
    replace content that the user may have edited; needs conflict handling

The provenance manifest is a substrate for the three-zone merge system
(Phase 2.2) — this module provides the recording and classification
primitives only.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

# Line-ending normalization: hash the logical content so a file written on
# Windows (CRLF) and later inspected on Linux (LF) produces the same digest.
# Mirrors Git's "text" attribute normalization for the one operation we care
# about here (integrity check), without disturbing the file on disk.


ProvenanceOrigin = Literal["base-template", "fragment", "user"]


@dataclass(frozen=True)
class ProvenanceRecord:
    """One tracked file's origin and integrity signature.

    ``origin`` distinguishes who emitted the file:
      * ``base-template`` — rendered from a Copier template (``services/{backend}/``, etc.)
      * ``fragment`` — emitted by a fragment's ``files/`` or ``inject.yaml``
      * ``user`` — user-authored, never touched by forge

    ``fragment_name`` and ``fragment_version`` are populated only when
    ``origin == "fragment"``. ``sha256`` is the hex digest of the
    content at emission time (CRLF normalized to LF).
    """

    origin: ProvenanceOrigin
    sha256: str
    fragment_name: str | None = None
    fragment_version: str | None = None


@dataclass
class ProvenanceCollector:
    """Accumulates provenance records during a generation run.

    Passed through generator + feature_injector to record every write.
    Paths are stored relative to the project root (as POSIX strings) so
    the manifest is portable across OSes.
    """

    project_root: Path
    records: dict[str, ProvenanceRecord] = field(default_factory=dict)

    def record(
        self,
        path: Path,
        *,
        origin: ProvenanceOrigin,
        fragment_name: str | None = None,
        fragment_version: str | None = None,
    ) -> None:
        """Record provenance for a file that has just been written to disk."""
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
        )

    def as_dict(self) -> dict[str, dict[str, str]]:
        """Return the collector's state in a TOML-serializable shape.

        Each entry becomes a sub-table in ``[forge.provenance]`` keyed by
        the relative path. ``None`` fields are omitted so the emitted
        TOML stays lean.
        """
        out: dict[str, dict[str, str]] = {}
        for key, rec in sorted(self.records.items()):
            entry: dict[str, str] = {"origin": rec.origin, "sha256": rec.sha256}
            if rec.fragment_name:
                entry["fragment_name"] = rec.fragment_name
            if rec.fragment_version:
                entry["fragment_version"] = rec.fragment_version
            out[key] = entry
        return out


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
      (skip, warn, three-way merge, back-up-and-replace — 2.2 scope).
    """
    if not path.is_file():
        return "missing"
    current = sha256_of(path)
    if current == recorded.sha256:
        return "unchanged"
    return "user-modified"
