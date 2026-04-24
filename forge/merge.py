"""Three-way merge for ``merge``-zone injections (A3-1 / Phase 2.2).

Every time a ``merge``-zone injection is applied, the rendered block's
content-hash is recorded in ``forge.toml`` under ``[forge.merge_blocks]``.
On re-apply, we compare three hashes:

    * ``baseline_sha``  — what forge emitted last time (from forge.toml)
    * ``current_sha``   — what's on disk right now (between the BEGIN/END
                          sentinels), after any user edits
    * ``new_sha``       — what the fragment would emit this time

Decision table:

    current_sha == baseline_sha  → safe overwrite (user didn't touch this block)
    new_sha      == baseline_sha  → no change in fragment; skip (keep user edits)
    current_sha == new_sha        → no-op; already up to date
    otherwise                     → conflict; write ``<target>.forge-merge``
                                    with the new block the fragment wanted,
                                    leave the target untouched

The sidecar ``.forge-merge`` file lets the user diff both versions and
resolve by hand. Since forge knows the block boundaries (BEGIN/END
sentinels) and each block's baseline, the sidecar contains only the
block body — not the whole file.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path


def sha256_of_text(text: str) -> str:
    """SHA-256 of a string with CRLF normalization (matches ``sha256_of``)."""
    normalized = text.replace("\r\n", "\n").encode("utf-8")
    return hashlib.sha256(normalized).hexdigest()


@dataclass(frozen=True)
class MergeBlockRecord:
    """One recorded block baseline.

    Keyed by ``{relative_path}::{feature_key}:{marker}`` in the manifest.
    ``sha256`` is the hash of the block body (content between BEGIN/END
    sentinels, exclusive of the sentinel lines themselves) at the time
    forge wrote it.
    """

    sha256: str


@dataclass
class MergeBlockCollector:
    """Accumulates merge-block records alongside provenance."""

    records: dict[str, MergeBlockRecord] = field(default_factory=dict)

    @staticmethod
    def key_for(rel_posix_path: str, feature_key: str, marker: str) -> str:
        """Canonical map key for a (file, feature, marker) tuple."""
        return f"{rel_posix_path}::{feature_key}:{marker.removeprefix('FORGE:')}"

    @staticmethod
    def parse_key(key: str) -> tuple[str, str, str] | None:
        """Inverse of :meth:`key_for`. Returns ``(rel_path, feature_key, marker)``.

        Epic F (1.1.0-alpha.1) uses this to walk ``[forge.merge_blocks]``
        when uninstalling a disabled fragment — the per-block records are
        the only structured hint forge has about which files hold
        sentinel-bounded injections after the fragment's own registry
        entry is gone.

        Returns ``None`` when the string doesn't match the canonical
        shape (e.g. a pre-1.0.0a3 key, a hand-edited manifest).
        """
        sep = "::"
        if sep not in key:
            return None
        rel, tail = key.split(sep, 1)
        if ":" not in tail:
            return None
        feature_key, marker_bare = tail.split(":", 1)
        # The stored form has the FORGE: prefix stripped; restore it so
        # downstream code sees the same shape ``_Injection.marker`` holds.
        marker = f"FORGE:{marker_bare}"
        return rel, feature_key, marker

    def record(
        self,
        *,
        rel_posix_path: str,
        feature_key: str,
        marker: str,
        block_body: str,
    ) -> None:
        key = self.key_for(rel_posix_path, feature_key, marker)
        self.records[key] = MergeBlockRecord(sha256=sha256_of_text(block_body))

    def as_dict(self) -> dict[str, dict[str, str]]:
        """TOML-serializable representation for ``[forge.merge_blocks]``."""
        out: dict[str, dict[str, str]] = {}
        for key, rec in sorted(self.records.items()):
            out[key] = {"sha256": rec.sha256}
        return out


@dataclass(frozen=True)
class MergeOutcome:
    """What happened when a merge-zone injection was re-applied.

    ``action`` is one of:
      * ``applied`` — block was rewritten (current matched baseline)
      * ``skipped-no-change`` — fragment snippet unchanged since baseline
      * ``skipped-idempotent`` — current already equals new
      * ``conflict`` — a ``.forge-merge`` sidecar was emitted; target untouched
      * ``no-baseline`` — first apply, baseline not yet recorded; behaved like generated
    """

    action: str
    sidecar_path: Path | None = None


def three_way_decide(
    *,
    baseline_sha: str | None,
    current_body: str,
    new_body: str,
) -> str:
    """Return the three-way decision (``applied`` / ``skipped-*`` / ``conflict``)
    without touching disk. Callers do the I/O; this function is pure.
    """
    new_sha = sha256_of_text(new_body)
    current_sha = sha256_of_text(current_body)

    if baseline_sha is None:
        # First time this merge-zone block is applied for this project —
        # no baseline to compare against. Behave like generated (apply).
        return "no-baseline"

    if current_sha == new_sha:
        return "skipped-idempotent"
    if current_sha == baseline_sha:
        return "applied"
    if new_sha == baseline_sha:
        return "skipped-no-change"
    return "conflict"


def write_sidecar(target: Path, new_block: str, tag: str) -> Path:
    """Emit a ``<target>.forge-merge`` sidecar listing the desired new block.

    The sidecar is a plain text file the user can ``git diff`` against
    the current target. Format is intentionally simple — no three-way
    patch syntax; just the block forge wanted to write, annotated with
    the conflict tag.
    """
    sidecar = target.with_suffix(target.suffix + ".forge-merge")
    body = (
        f"# forge merge conflict — tag: {tag}\n"
        f"# target: {target.name}\n"
        "# \n"
        "# The block below is what forge wanted to write. Your current\n"
        "# file contents differ from both this version AND the baseline\n"
        "# forge last wrote, so the generator cannot safely pick a\n"
        "# resolution. Merge by hand, then delete this sidecar.\n"
        "\n"
        f"{new_block}"
    )
    sidecar.write_text(body, encoding="utf-8")
    return sidecar
