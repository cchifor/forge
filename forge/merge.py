"""Three-way merge for ``merge``-zone injections (A3-1 / Phase 2.2).

Every time a ``merge``-zone injection is applied, the rendered block's
content-hash is recorded in ``forge.toml`` under ``[forge.merge_blocks]``.
On re-apply, we compare three hashes:

    * ``baseline_sha``  — what forge emitted last time (from forge.toml)
    * ``current_sha``   — what's on disk right now (between the BEGIN/END
                          sentinels), after any user edits
    * ``new_sha``       — what the fragment would emit this time

Decision table (forward / ``forge --update`` direction):

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

Direction-agnostic core (Phase 2 of the bidirectional-sync plan)
-----------------------------------------------------------------

The decision is fundamentally symmetric: given a common baseline and two
candidate bodies (call them A and B), the question is which of the two
moved away from baseline. The asymmetry sits in the policy mapping, not
the comparison.

``symmetric_three_way_decide`` (and its file-level twin) returns one of
five direction-neutral outcomes:

    * ``no-baseline``        — baseline_sha is None
    * ``converged``          — A == B (both moved together, or both at
                                baseline)
    * ``a-only-changed``     — A != baseline, B == baseline
    * ``b-only-changed``     — A == baseline, B != baseline
    * ``conflict``           — A != B, both != baseline

Forward direction (``forge --update``, ``three_way_decide``): A is the
user's current on-disk body, B is what the fragment would emit. We
preserve user edits (``a-only-changed → skipped-no-change``) and apply
fragment changes (``b-only-changed → applied``).

Reverse direction (``forge --harvest``, Phase 4, ``reverse_three_way_decide``):
A is the user's current on-disk body, B is the upstream fragment body.
The roles flip — a user edit is now the candidate for harvest
(``a-only-changed → safe-apply``), and an upstream-only change is a
benign skip (``b-only-changed → skipped-no-change``). ``conflict``
remains conflict in both directions; ``converged`` and ``no-baseline``
are direction-neutral.

This module exposes both wrappers so the call sites stay declarative —
the forward applier doesn't think about harvest, the harvest planner
doesn't think about applies.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

# Public symbolic outcomes returned by the direction-agnostic core. Each
# corresponds to one quadrant of (A vs baseline, B vs baseline) with the
# diagonal ``A == B`` collapsed into ``converged``.
SymmetricDecision = Literal[
    "no-baseline",
    "converged",
    "a-only-changed",
    "b-only-changed",
    "conflict",
]

# Outcomes the forward (``forge --update``) wrapper returns. Existing
# applier call sites pattern-match against these strings.
ForwardDecision = Literal[
    "no-baseline",
    "skipped-idempotent",
    "applied",
    "skipped-no-change",
    "conflict",
]

# Outcomes the reverse (``forge --harvest``, Phase 4) wrapper returns.
# ``safe-apply`` is the candidate-for-promotion case — the user moved,
# the fragment didn't, so the harvest planner has a clean signal.
ReverseDecision = Literal[
    "no-baseline",
    "skipped-idempotent",
    "safe-apply",
    "skipped-no-change",
    "conflict",
]


# Forward-direction policy mapping: how the symmetric outcomes translate
# to the language existing appliers speak. Kept as a module-level table
# so ``three_way_decide`` is literally one dict lookup over the core.
_FORWARD_MAP: dict[SymmetricDecision, ForwardDecision] = {
    "no-baseline": "no-baseline",
    "converged": "skipped-idempotent",
    "a-only-changed": "skipped-no-change",  # user edited, fragment didn't
    "b-only-changed": "applied",  # fragment moved, user didn't
    "conflict": "conflict",
}

# Reverse-direction policy mapping: roles of "A moved" and "B moved" flip
# relative to ``_FORWARD_MAP``. A user-only edit becomes a candidate for
# harvest; an upstream-only change becomes a benign skip.
_REVERSE_MAP: dict[SymmetricDecision, ReverseDecision] = {
    "no-baseline": "no-baseline",
    "converged": "skipped-idempotent",
    "a-only-changed": "safe-apply",  # user edited, upstream didn't
    "b-only-changed": "skipped-no-change",  # upstream moved, user didn't
    "conflict": "conflict",
}


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


def symmetric_three_way_decide(
    *,
    baseline_sha: str | None,
    a_body: str,
    b_body: str,
) -> SymmetricDecision:
    """Direction-agnostic three-way classification for two text bodies.

    Returns one of the five :data:`SymmetricDecision` outcomes:

    * ``no-baseline`` — ``baseline_sha`` is ``None`` (the manifest has no
      record for this block); both directions treat this as
      "not enough information".
    * ``converged`` — A and B have the same content hash (whether or not
      that hash equals the baseline). Nothing to reconcile.
    * ``a-only-changed`` — A has moved off baseline; B still matches it.
    * ``b-only-changed`` — B has moved off baseline; A still matches it.
    * ``conflict`` — both moved divergently.

    The mapping to forward (apply) and reverse (harvest) policy lives in
    the wrappers :func:`three_way_decide` and :func:`reverse_three_way_decide`.
    Callers that want raw symmetry — Phase 4 planners, diagnostics —
    should call this directly.

    Pure over the inputs; no disk I/O.
    """
    if baseline_sha is None:
        return "no-baseline"

    a_sha = sha256_of_text(a_body)
    b_sha = sha256_of_text(b_body)

    # Idempotent: both sides agree. Whether or not they match baseline
    # is irrelevant — there's nothing to reconcile.
    if a_sha == b_sha:
        return "converged"

    a_moved = a_sha != baseline_sha
    b_moved = b_sha != baseline_sha

    if a_moved and not b_moved:
        return "a-only-changed"
    if b_moved and not a_moved:
        return "b-only-changed"
    # Both moved, and (since a_sha != b_sha) they disagree.
    return "conflict"


def three_way_decide(
    *,
    baseline_sha: str | None,
    current_body: str,
    new_body: str,
) -> ForwardDecision:
    """Forward (``forge --update``) wrapper around :func:`symmetric_three_way_decide`.

    Returns the existing forward-direction vocabulary
    (``applied`` / ``skipped-*`` / ``conflict`` / ``no-baseline``) so all
    existing appliers keep working byte-identically. ``current_body`` is
    the user's on-disk text; ``new_body`` is what the fragment wants to
    emit. See module docstring for the direction-asymmetry rationale.
    """
    decision = symmetric_three_way_decide(
        baseline_sha=baseline_sha,
        a_body=current_body,
        b_body=new_body,
    )
    return _FORWARD_MAP[decision]


def reverse_three_way_decide(
    *,
    baseline_sha: str | None,
    current_body: str,
    upstream_body: str,
) -> ReverseDecision:
    """Reverse (``forge --harvest``, Phase 4) wrapper.

    The arguments mirror :func:`three_way_decide` but the policy mapping
    flips: a user-only edit (``current`` diverged, ``upstream`` didn't)
    is the **candidate for harvest** (``safe-apply``); an upstream-only
    change (``upstream`` diverged, ``current`` didn't) is the safe skip
    (``skipped-no-change``) because the user has no local work to
    promote. See :data:`_REVERSE_MAP` for the full table.

    Pure; no disk I/O. The harvest planner decides what to do with
    ``safe-apply`` candidates — write a proposal, surface to the user,
    etc. — at the call site.
    """
    decision = symmetric_three_way_decide(
        baseline_sha=baseline_sha,
        a_body=current_body,
        b_body=upstream_body,
    )
    return _REVERSE_MAP[decision]


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


# ---------------------------------------------------------------------------
# File-level three-way merge (P0.1, 1.1.0-alpha.2)
# ---------------------------------------------------------------------------
#
# Mirror of the block-level three-way merge above, but for whole files
# copied verbatim from a fragment's ``files/`` tree. Used by
# :mod:`forge.appliers.files` on the ``forge --update`` path so a fragment
# that ships a bug-fix to ``files/auth/middleware.py`` actually reaches
# existing projects, instead of being silently skipped because the file
# already exists. Pre-1.1 the updater passed ``skip_existing_files=True``
# unconditionally — see ``updater.py``'s deferral comment removed in this
# epic.
#
# Hashes feed the same decision table as :func:`three_way_decide`, with
# two extra rows for the file-level cases that don't apply to inline
# blocks: "user deleted the file" (still a baseline; current is None) and
# "no baseline at all" (pre-1.0 generation; treat as user-authored).


_BINARY_SAMPLE_BYTES = 8192


def _looks_binary(sample: bytes) -> bool:
    """Null-byte heuristic Git uses for "is this file text or binary?"."""
    return b"\x00" in sample


def is_binary_file(path: Path) -> bool:
    """Return ``True`` when ``path`` looks like binary content.

    Reads at most :data:`_BINARY_SAMPLE_BYTES` from the head of the file,
    matching Git's ``buffer_is_binary`` heuristic. Returns ``False`` for
    missing or empty files (caller decides whether that case is binary
    in context).
    """
    if not path.is_file():
        return False
    with path.open("rb") as fh:
        sample = fh.read(_BINARY_SAMPLE_BYTES)
    return _looks_binary(sample)


def sha256_of_file(path: Path) -> str:
    """SHA-256 of ``path``'s contents, with CRLF normalisation for text.

    Text files (no null byte in the head sample, decode as UTF-8) get the
    same CRLF→LF normalisation as :func:`sha256_of_text`, so a fragment
    file checked-in with LF line endings round-trips cleanly through a
    Windows working tree. Binary files (or files that don't decode as
    UTF-8) hash the raw bytes — line-ending normalisation would corrupt
    them.
    """
    data = path.read_bytes()
    if _looks_binary(data[:_BINARY_SAMPLE_BYTES]):
        return hashlib.sha256(data).hexdigest()
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return hashlib.sha256(data).hexdigest()
    return sha256_of_text(text)


@dataclass(frozen=True)
class FileMergeOutcome:
    """What happened when a fragment-authored file was re-applied on update.

    Mirror of :class:`MergeOutcome` at file granularity. ``action`` is
    one of:
      * ``applied`` — file written (fresh emit, clean overwrite, or
        user-deleted re-emit)
      * ``skipped-idempotent`` — current already equals new
      * ``skipped-no-change`` — fragment unchanged since baseline; user
        edits preserved
      * ``conflict`` — ``.forge-merge`` (or ``.forge-merge.bin``) sidecar
        emitted; target untouched
      * ``no-baseline`` — pre-1.1 generation or otherwise untracked file;
        preserved as if user-authored (``skip_existing`` semantics)
    """

    action: str
    target: Path
    sidecar_path: Path | None = None


def symmetric_file_three_way_decide(
    *,
    baseline_sha: str,
    a_sha: str,
    b_sha: str,
) -> SymmetricDecision:
    """Direction-agnostic file-level classification.

    The all-present (no missing file) analogue of
    :func:`symmetric_three_way_decide` operating on pre-computed SHAs.
    Both ``a_sha`` and ``b_sha`` are non-``None`` strings, and
    ``baseline_sha`` is the recorded baseline. ``None`` baselines and
    ``None`` ``current_sha`` (user-deleted) are direction-specific edge
    cases handled by the wrappers; the symmetric core takes the clean
    three-hash case only.

    Returns one of :data:`SymmetricDecision` minus ``no-baseline``
    (callers gate on that case before calling).
    """
    if a_sha == b_sha:
        return "converged"

    a_moved = a_sha != baseline_sha
    b_moved = b_sha != baseline_sha

    if a_moved and not b_moved:
        return "a-only-changed"
    if b_moved and not a_moved:
        return "b-only-changed"
    return "conflict"


def file_three_way_decide(
    *,
    baseline_sha: str | None,
    current_sha: str | None,
    new_sha: str,
) -> ForwardDecision:
    """Forward (``forge --update``) three-way decision for a fragment-authored file.

    Pure function over content hashes — caller does the file I/O. The
    decision table covers all 7 (baseline × current × new) combinations
    that matter:

    +-------------+-------------+---------+----------------------+
    | baseline    | current     | new     | action               |
    +=============+=============+=========+======================+
    | None        | None        | *       | applied              |
    | None        | exists      | *       | no-baseline          |
    | sha         | None        | *       | applied              |
    | sha         | == baseline | == base | skipped-idempotent   |
    | sha         | == baseline | new     | applied              |
    | sha         | other       | == base | skipped-no-change    |
    | sha         | other       | other   | conflict             |
    +-------------+-------------+---------+----------------------+

    The ``no-baseline`` row is the file-level analogue of the same
    branch in :func:`three_way_decide`: a file the manifest doesn't
    track is treated as user-authored and preserved. This makes the
    flip from ``skip_existing_files=True`` (pre-1.1) to ``--mode merge``
    (1.1+) safe for projects that haven't yet adopted SHA baselines.

    Only the all-three-present case delegates to
    :func:`symmetric_file_three_way_decide`; the missing-baseline and
    missing-current rows are file-level edge cases the inline-block path
    doesn't have.
    """
    # No baseline tracked at all. If nothing on disk, fresh emit.
    # Otherwise the file pre-dates SHA tracking — preserve it.
    if baseline_sha is None:
        if current_sha is None:
            return "applied"
        return "no-baseline"

    # Baseline exists but the user deleted the file. Re-emit; users who
    # want it gone should disable the fragment, not delete the file.
    if current_sha is None:
        return "applied"

    # All three present — delegate to the symmetric core, then map.
    decision = symmetric_file_three_way_decide(
        baseline_sha=baseline_sha,
        a_sha=current_sha,
        b_sha=new_sha,
    )
    return _FORWARD_MAP[decision]


def reverse_file_three_way_decide(
    *,
    baseline_sha: str | None,
    current_sha: str | None,
    upstream_sha: str,
) -> ReverseDecision:
    """Reverse (``forge --harvest``) three-way decision for a fragment-authored file.

    Mirror of :func:`file_three_way_decide` for the harvest direction.
    Edge cases:

    * ``baseline_sha is None`` → ``no-baseline`` — without a baseline we
      cannot identify what's a user edit vs. an untracked legacy file,
      so we surface nothing to harvest.
    * ``current_sha is None`` (user deleted the file) → ``safe-apply``
      — the deletion is itself a candidate signal; harvest may propose
      removing the fragment file. The decide function classifies this
      as a safe candidate to surface; the **call site** in Phase 4 is
      responsible for tagging the proposal as "needs review" (this is
      the most destructive harvest outcome).
    * All-present → delegate to :func:`symmetric_file_three_way_decide`
      with ``a_sha=current_sha``, ``b_sha=upstream_sha``, then map via
      :data:`_REVERSE_MAP` (``a-only-changed → safe-apply``,
      ``b-only-changed → skipped-no-change``,
      ``converged → skipped-idempotent``, ``conflict → conflict``).

    Returns one of :data:`ReverseDecision`.
    """
    if baseline_sha is None:
        return "no-baseline"

    if current_sha is None:
        # User deleted a fragment-tracked file. Harvest can surface this
        # as a candidate for removal; the call site decides whether to
        # auto-promote or tag for review.
        return "safe-apply"

    decision = symmetric_file_three_way_decide(
        baseline_sha=baseline_sha,
        a_sha=current_sha,
        b_sha=upstream_sha,
    )
    return _REVERSE_MAP[decision]


def write_file_sidecar(
    target: Path,
    new_content: str | bytes,
    *,
    tag: str,
) -> Path:
    """Emit a ``<target>.forge-merge`` sidecar with the desired new file.

    Counterpart to :func:`write_sidecar` at file granularity. Text
    content goes to ``<target>.forge-merge`` with the same comment-style
    header the block sidecar uses; binary content goes to
    ``<target>.forge-merge.bin`` with no header (the bytes are the
    payload — no consumer can ignore a banner).

    Returns the path written so callers can record it on the
    :class:`FileMergeOutcome`.
    """
    if isinstance(new_content, bytes):
        sidecar = target.with_suffix(target.suffix + ".forge-merge.bin")
        sidecar.write_bytes(new_content)
        return sidecar
    sidecar = target.with_suffix(target.suffix + ".forge-merge")
    body = (
        f"# forge merge conflict — tag: {tag}\n"
        f"# target: {target.name}\n"
        "# \n"
        "# The content below is what forge wanted to write. Your current\n"
        "# file contents differ from both this version AND the baseline\n"
        "# forge last wrote, so the generator cannot safely pick a\n"
        "# resolution. Merge by hand, then delete this sidecar.\n"
        "\n"
        f"{new_content}"
    )
    sidecar.write_text(body, encoding="utf-8")
    return sidecar
