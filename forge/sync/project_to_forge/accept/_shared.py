"""Shared types + helpers for the accept package.

Split out from the original ``accept.py`` god module — see
:mod:`forge.sync.project_to_forge.accept` for the public surface.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO, Any, Literal

from forge.fragments import FRAGMENT_REGISTRY
from forge.sync.merge import sha256_of_file


# Action vocabulary. ``restamped-baseline`` is the success case — the
# manifest entry now reflects the user's edit. The two skip variants
# capture the most common bundle states we encounter:
#
# * ``skipped-unchanged``    — manifest already matches the project state
#                              (idempotent re-run / bundle was already accepted).
# * ``skipped-not-applied``  — upstream fragment still emits the pre-edit
#                              body. The bundle hasn't landed yet; nothing
#                              to re-stamp without losing the user's signal.
# * ``error``                — one specific candidate couldn't be processed
#                              (manifest entry missing, target file gone,
#                              etc.). Other candidates in the same bundle
#                              are still processed; the report aggregates.
AcceptHarvestedAction = Literal[
    "restamped-baseline",
    "skipped-unchanged",
    "skipped-not-applied",
    "error",
]
"""Per-entry action surfaced in :class:`AcceptHarvestedEntry`."""

# Candidate kinds the v1 accept-harvested path acts on. ``block`` /
# ``files`` / ``new-file`` are first-class. ``deps`` / ``env`` are
# surfaced as ``skipped-not-applied`` with a "not yet implemented"
# rationale, mirroring :func:`apply_bundle_to_fragments`.
AcceptHarvestedKind = Literal["block", "files", "deps", "env", "new-file"]
"""Per-entry kind surfaced in :class:`AcceptHarvestedEntry`."""


# Risk classifications the accept step considers by default. Mirrors the
# CLI's ``--accept-risk-filter`` default and the apply-bundle helper's
# default risk filter. Operators wanting to re-stamp ``needs-review``
# candidates as well pass an explicit filter.
_DEFAULT_RISK_FILTER: tuple[str, ...] = ("safe-apply",)


@dataclass(frozen=True)
class AcceptHarvestedEntry:
    """One candidate's disposition after the accept step.

    Attributes:
        target_path: Manifest key (``rel_path`` for files candidates;
            ``rel_path::feature_key:marker`` for blocks). What appears
            in :attr:`AcceptHarvestedReport.render_human` rows.
        kind: Candidate kind. Mirrors :attr:`CandidatePatch.kind`.
        action: One of :data:`AcceptHarvestedAction`. ``restamped-baseline``
            is the success case; the rest are diagnostic.
        reason: Free-form note from the accept step. For
            ``skipped-not-applied`` it explains *why* (fragment registry
            mismatch, upstream still emits old body, etc.). For ``error``
            it carries the underlying failure.
        new_sha: SHA the manifest now records for this entry. Empty for
            anything other than ``restamped-baseline``.
        old_sha: SHA the manifest carried before the accept step. Useful
            for diagnostics and the JSON envelope's audit trail.
    """

    target_path: str
    kind: str
    action: str
    reason: str = ""
    new_sha: str = ""
    old_sha: str = ""

    def as_dict(self) -> dict[str, Any]:
        """JSON-serializable form for the CLI ``--json`` envelope."""
        out: dict[str, Any] = {
            "target_path": self.target_path,
            "kind": self.kind,
            "action": self.action,
        }
        if self.reason:
            out["reason"] = self.reason
        if self.new_sha:
            out["new_sha"] = self.new_sha
        if self.old_sha:
            out["old_sha"] = self.old_sha
        return out


@dataclass(frozen=True)
class AcceptHarvestedReport:
    """Aggregate result of :func:`accept_harvested`.

    Attributes:
        bundle_id: The bundle id from the input bundle's ``manifest.json``.
            Empty when the bundle was unreadable / malformed.
        project_root: Absolute path to the project whose ``forge.toml``
            was (or would have been) re-stamped. Recorded so JSON
            consumers can confirm the operation target.
        entries: Per-candidate disposition. Sorted alphabetically by
            ``target_path`` for deterministic output.
        errors: Bundle-level errors. Non-empty when the bundle file is
            missing, the manifest.json is malformed, or the project's
            own ``forge.toml`` couldn't be read. The CLI maps a non-empty
            ``errors`` to a non-zero exit code; per-candidate errors live
            in :attr:`entries` and don't trip the bundle-level signal.
        restamped: Count of ``restamped-baseline`` entries — the
            success-case counter the round-trip CI lane checks.
        skipped: Count of ``skipped-unchanged`` and ``skipped-not-applied``
            entries combined. The accept verb skips silently in
            single-line human output but the JSON envelope distinguishes
            the two via the per-entry ``action`` field.
        errored: Count of ``error`` entries (per-candidate failures).
    """

    bundle_id: str
    project_root: Path
    entries: tuple[AcceptHarvestedEntry, ...] = field(default_factory=tuple)
    errors: tuple[str, ...] = field(default_factory=tuple)
    restamped: int = 0
    skipped: int = 0
    errored: int = 0

    def to_dict(self) -> dict[str, Any]:
        """JSON-serializable form for the CLI ``--json`` envelope."""
        return {
            "bundle_id": self.bundle_id,
            "project_root": str(self.project_root),
            "restamped": self.restamped,
            "skipped": self.skipped,
            "errored": self.errored,
            "entries": [e.as_dict() for e in self.entries],
            "errors": list(self.errors),
        }

    def render_human(self, stream: IO[str]) -> None:
        """Render a one-line summary + per-candidate sample to ``stream``.

        Caps the per-candidate sample at 20 lines so a bundle covering
        thousands of records doesn't flood the terminal — JSON output is
        the canonical channel for full inventories.
        """
        if self.errors:
            stream.write(f"forge accept-harvested: bundle error ({len(self.errors)})\n")
            for err in self.errors[:20]:
                stream.write(f"  ! {err}\n")
            return

        stream.write(
            f"forge accept-harvested: restamped={self.restamped} "
            f"skipped={self.skipped} errored={self.errored} "
            f"(bundle_id={self.bundle_id or '<unknown>'})\n"
        )

        sample_cap = 20
        emitted = 0
        for entry in self.entries:
            if emitted >= sample_cap:
                break
            if entry.action == "skipped-unchanged":
                continue  # idempotent no-ops are noise; suppress in human output.
            marker = {
                "restamped-baseline": "+",
                "skipped-not-applied": " ",
                "error": "!",
            }.get(entry.action, " ")
            note = f"  ({entry.reason})" if entry.reason else ""
            stream.write(f"  {marker} {entry.target_path} [{entry.action}]{note}\n")
            emitted += 1
        remaining = len(self.entries) - emitted
        if remaining > sample_cap:
            stream.write(f"  ... and {remaining - sample_cap} more (use --json for full output)\n")


def _read_bundle_manifest(bundle_path: Path) -> tuple[dict[str, Any], list[str]]:
    """Load and shape-check ``<bundle_path>/manifest.json``.

    Returns ``(parsed_dict, errors)``. When ``errors`` is non-empty the
    caller treats the bundle as unusable and surfaces a bundle-level
    error report. The parsed dict carries the verbatim envelope
    :meth:`HarvestBundle.to_dict` produced (or close enough — we only
    rely on ``bundle_id`` and ``candidates`` at the top level).
    """
    if not bundle_path.exists():
        return {}, [f"bundle path does not exist: {bundle_path}"]
    if not bundle_path.is_dir():
        return {}, [f"bundle path is not a directory: {bundle_path}"]
    manifest_file = bundle_path / "manifest.json"
    if not manifest_file.is_file():
        return {}, [f"bundle manifest.json missing at {manifest_file}"]
    try:
        raw = manifest_file.read_text(encoding="utf-8")
    except OSError as e:
        return {}, [f"bundle manifest.json unreadable: {e}"]
    try:
        doc = json.loads(raw)
    except json.JSONDecodeError as e:
        return {}, [f"bundle manifest.json malformed JSON: {e}"]
    if not isinstance(doc, dict):
        return {}, [f"bundle manifest.json root must be an object (got {type(doc).__name__})"]
    if "candidates" not in doc:
        return {}, ["bundle manifest.json missing required 'candidates' field"]
    return doc, []


def _resolve_upstream_file_sha(
    *,
    fragment_name: str,
    rel_path: str,
) -> str | None:
    """SHA of the fragment-shipped file at ``<fragment_dir>/files/<rel>``.

    Walks the fragment's implementations until one of them ships a
    file at ``rel_path``. Returns ``sha256_of_file(...)`` for the first
    match, or ``None`` when no impl carries the file. The ``None``
    result signals "bundle not yet landed" to the caller.
    """
    fragment = FRAGMENT_REGISTRY.get(fragment_name)
    if fragment is None or not fragment.implementations:
        return None

    try:
        from forge.fragments import _resolve_fragment_dir
    except ImportError:
        return None

    for impl in fragment.implementations.values():
        try:
            fragment_dir = _resolve_fragment_dir(impl.fragment_dir)
        except Exception:  # noqa: BLE001
            continue
        candidate = fragment_dir / "files" / rel_path
        if candidate.is_file():
            return sha256_of_file(candidate)
    return None


def _resolve_fragment_version(fragment_name: str) -> str | None:
    """Resolve the current forge-side version for a fragment.

    Today fragments don't carry a per-fragment semver (``Fragment`` /
    ``FragmentImplSpec`` have no ``version`` field), so the canonical
    "fragment_version" recorded in ``forge.toml`` is the running forge
    package version — same convention the migration / forward applier
    paths use. Returns ``None`` when the fragment isn't in the registry
    so the caller leaves the manifest entry's ``fragment_version`` alone
    rather than over-stamping it with a guess.
    """
    fragment = FRAGMENT_REGISTRY.get(fragment_name)
    if fragment is None:
        return None
    # Prefer an explicit ``version`` attribute on the impl when the
    # fragment author has wired one (plugin SDK convention). Falls back
    # to the forge package version so the manifest entry is at least
    # consistent with the rest of v2 provenance.
    for impl in fragment.implementations.values():
        version = getattr(impl, "version", None)
        if version:
            return str(version)
    try:
        import forge  # noqa: PLC0415 — module-level import would create a cycle.
    except ImportError:
        return None
    return str(getattr(forge, "__version__", "")) or None
