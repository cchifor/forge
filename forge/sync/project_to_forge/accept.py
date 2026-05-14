"""Re-stamp forge.toml baselines after a harvest bundle lands upstream (Phase 6).

The Story B round-trip closes here. The forward flow is:

    1. User runs ``forge --harvest`` → bundle on disk.
    2. User (or a maintainer) lands the candidate patches upstream
       (``forge --emit-pr`` or by hand).
    3. The forge maintainer reviews + merges.
    4. The user pulls the new forge release.
    5. The user runs ``forge --accept-harvested <bundle>``.

Step 5 — this module — re-stamps the project's ``forge.toml`` so the
user's edits become the new baseline. Without it, every subsequent
``forge --verify`` would re-classify the user's blocks as
``user-modified`` against the now-upstream fragment baseline and
``forge --update`` would emit ``.forge-merge`` sidecars complaining the
user "drifted" from what is now their own contributed snippet.

The contract is intentionally narrow: we only re-stamp records the
bundle covered, and only when we can verify the upstream fragment has
actually been updated to match the user's edit (i.e. the round-trip
actually completed). Bundles that were generated but not yet landed
upstream surface as ``skipped-not-applied`` — running
``--accept-harvested`` is then a no-op rather than a silent baseline
shift.

This module is read-only against the bundle (the on-disk
``manifest.json`` layout produced by :mod:`forge.sync.project_to_forge.bundle`
is the input contract); the only thing it writes is the project's own
``forge.toml`` via :func:`forge.sync.manifest.write_forge_toml` (which
preserves schema v2 invariants — template_versions etc.).
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO, Any, Literal

from forge.fragments import FRAGMENT_REGISTRY
from forge.injectors.sentinels import _read_block_body
from forge.sync.manifest import read_forge_toml, write_forge_toml
from forge.sync.merge import MergeBlockCollector, sha256_of_file, sha256_of_text

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


def accept_harvested(
    project_root: Path,
    bundle_path: Path,
    *,
    risk_filter: tuple[str, ...] = _DEFAULT_RISK_FILTER,
    quiet: bool = False,
) -> AcceptHarvestedReport:
    """Re-stamp the project's ``forge.toml`` after a harvest bundle landed upstream.

    Reads ``<bundle_path>/manifest.json`` (the layout
    :func:`forge.sync.project_to_forge.bundle.write_bundle` produces),
    walks each candidate, and for those whose risk is in ``risk_filter``:

    * **Block candidates** — locate the project file, read the current
      block body via :func:`forge.injectors.sentinels._read_block_body`,
      compare against the bundle's recorded ``current_sha`` and the
      upstream fragment's rendered snippet. When the upstream snippet
      matches the user's body, the bundle has landed → re-stamp the
      manifest's ``merge_blocks`` entry's ``sha256`` (and bump the
      ``fragment_version`` from the registry when available). Otherwise
      surface as ``skipped-not-applied``.
    * **Files candidates** — re-compute the project file's SHA. If the
      fragment-shipped file (under ``<fragment_dir>/files/<rel>``) now
      hashes to the same value, the bundle has landed → re-stamp the
      manifest's ``provenance`` entry. Otherwise ``skipped-not-applied``.
    * **deps / env candidates** — emitted as ``skipped-not-applied``
      with the rationale that structural manifest reasoning hasn't been
      wired yet (matches :func:`apply_bundle_to_fragments`'s deferral).
    * **new-file candidates** — re-stamp the manifest's ``provenance``
      entry to mark the file as fragment-owned now that upstream ships it.

    Args:
        project_root: Project the bundle was extracted from. Must
            contain a ``forge.toml`` — missing / malformed manifest
            surfaces as a bundle-level error (``report.errors``
            non-empty).
        bundle_path: Directory containing the bundle ``manifest.json``.
            Per :class:`HarvestBundle.write`'s layout.
        risk_filter: Subset of the candidate-risk vocabulary the accept
            step considers. Defaults to ``("safe-apply",)`` — the
            auto-acceptable tier. Pass
            ``("safe-apply", "needs-review")`` to accept needs-review
            candidates as well.
        quiet: When ``False``, prints a one-line per-candidate progress
            note. Tests should pass ``True``.

    Returns:
        An :class:`AcceptHarvestedReport` carrying per-entry dispositions
        and aggregate counters. The CLI dispatcher maps a non-empty
        :attr:`AcceptHarvestedReport.errors` to a non-zero exit code
        (5 — the manifest-IO code).

    Never raises on individual candidate failures — those land as
    ``error`` entries. Only bundle-level failures (missing
    ``manifest.json``, unreadable ``forge.toml``) populate
    :attr:`AcceptHarvestedReport.errors`.
    """
    project_root = project_root.resolve()
    bundle_path = bundle_path.resolve()

    bundle_dict, bundle_errors = _read_bundle_manifest(bundle_path)
    if bundle_errors:
        return AcceptHarvestedReport(
            bundle_id="",
            project_root=project_root,
            entries=(),
            errors=tuple(bundle_errors),
        )

    bundle_id = str(bundle_dict.get("bundle_id", ""))
    candidates_raw = bundle_dict.get("candidates", [])
    if not isinstance(candidates_raw, list):
        return AcceptHarvestedReport(
            bundle_id=bundle_id,
            project_root=project_root,
            entries=(),
            errors=(
                f"bundle manifest.json: 'candidates' must be a list (got {type(candidates_raw).__name__})",
            ),
        )

    manifest_path = project_root / "forge.toml"
    try:
        data = read_forge_toml(manifest_path)
    except FileNotFoundError:
        return AcceptHarvestedReport(
            bundle_id=bundle_id,
            project_root=project_root,
            entries=(),
            errors=(f"no forge.toml at {project_root}",),
        )
    except ValueError as e:
        return AcceptHarvestedReport(
            bundle_id=bundle_id,
            project_root=project_root,
            entries=(),
            errors=(f"forge.toml malformed: {e}",),
        )

    # Working copies of the manifest tables. We mutate these in place
    # and write back once at the end so a partial failure leaves the
    # original ``forge.toml`` untouched.
    provenance = dict(data.provenance)
    merge_blocks = dict(data.merge_blocks)

    entries: list[AcceptHarvestedEntry] = []
    restamped = 0
    skipped = 0
    errored = 0
    any_change = False

    for cand_raw in candidates_raw:
        if not isinstance(cand_raw, dict):
            entries.append(
                AcceptHarvestedEntry(
                    target_path="<malformed>",
                    kind="",
                    action="error",
                    reason=f"candidate entry must be an object (got {type(cand_raw).__name__})",
                )
            )
            errored += 1
            continue

        # Filter by risk. Skipped-by-filter entries are recorded with
        # action="skipped-not-applied" so the report's audit trail shows
        # the reviewer "we saw this; here's why we didn't act".
        risk = str(cand_raw.get("risk", ""))
        if risk not in risk_filter:
            entries.append(
                AcceptHarvestedEntry(
                    target_path=str(
                        cand_raw.get("target_path", cand_raw.get("rel_path", "<unknown>"))
                    ),
                    kind=str(cand_raw.get("kind", "")),
                    action="skipped-not-applied",
                    reason=f"risk={risk!r} not in filter {risk_filter!r}",
                )
            )
            skipped += 1
            continue

        kind = str(cand_raw.get("kind", ""))
        if kind == "block":
            entry, changed = _accept_block(
                cand_raw,
                project_root=project_root,
                merge_blocks=merge_blocks,
            )
        elif kind == "files":
            entry, changed = _accept_files(
                cand_raw,
                project_root=project_root,
                provenance=provenance,
            )
        elif kind == "new-file":
            entry, changed = _accept_new_file(
                cand_raw,
                project_root=project_root,
                provenance=provenance,
            )
        elif kind in ("deps", "env"):
            # Structural manifest reasoning (which dependency field gets
            # the addition? which env stanza?) isn't wired into the
            # accept path yet — same rationale as
            # ``apply_bundle_to_fragments`` defers these in v1.
            entry = AcceptHarvestedEntry(
                target_path=str(cand_raw.get("target_path", cand_raw.get("rel_path", "<unknown>"))),
                kind=kind,
                action="skipped-not-applied",
                reason=f"{kind} re-stamp not yet implemented",
            )
            changed = False
        else:
            entry = AcceptHarvestedEntry(
                target_path=str(cand_raw.get("target_path", cand_raw.get("rel_path", "<unknown>"))),
                kind=kind,
                action="error",
                reason=f"unknown candidate kind {kind!r}",
            )
            changed = False

        entries.append(entry)
        any_change = any_change or changed
        if entry.action == "restamped-baseline":
            restamped += 1
        elif entry.action == "error":
            errored += 1
        else:
            skipped += 1

    # Write the manifest back only when something actually changed —
    # idempotent re-runs skip the disk hit and keep the file's mtime
    # stable (useful for caching-aware build systems).
    if any_change:
        write_forge_toml(
            manifest_path,
            version=data.version,
            project_name=data.project_name,
            templates=data.templates,
            options=data.options,
            provenance=provenance,
            merge_blocks=merge_blocks,
            template_versions=data.template_versions,
            schema_version=data.schema_version,
        )

    # Sort entries for deterministic output. The bundle's order is the
    # extractor pipeline's emission order, which isn't stable across
    # platforms (filesystem walk order). Sorting by target_path gives
    # callers a predictable shape.
    entries.sort(key=lambda e: (e.target_path, e.kind))

    if not quiet:
        print(
            f"  [accept-harvested] restamped={restamped} skipped={skipped} "
            f"errored={errored} (bundle_id={bundle_id or '<unknown>'})"
        )

    return AcceptHarvestedReport(
        bundle_id=bundle_id,
        project_root=project_root,
        entries=tuple(entries),
        errors=(),
        restamped=restamped,
        skipped=skipped,
        errored=errored,
    )


# ---------------------------------------------------------------------------
# Bundle reader
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Per-kind accept handlers
# ---------------------------------------------------------------------------


def _accept_block(
    cand: Mapping[str, Any],
    *,
    project_root: Path,
    merge_blocks: dict[str, dict[str, Any]],
) -> tuple[AcceptHarvestedEntry, bool]:
    """Re-stamp the manifest's ``merge_blocks`` entry for a block candidate.

    Resolves the manifest key from the candidate's
    ``(target_path, feature_key, marker)`` triple, reads the on-disk
    block body via :func:`_read_block_body`, and compares it against the
    upstream fragment's rendered snippet (via the FRAGMENT_REGISTRY +
    inject.yaml). When upstream matches the user's body, the bundle
    has landed → re-stamp ``merge_blocks[key]['sha256']`` to the
    user's body's hash. Otherwise emit ``skipped-not-applied``.

    Returns ``(entry, changed)`` — the second element is True when the
    manifest's ``merge_blocks`` dict was mutated, so the caller knows
    whether to write back.
    """
    target_path = str(cand.get("target_path", ""))
    feature_key = str(cand.get("feature_key", ""))
    marker = str(cand.get("marker", ""))
    fragment_name = str(cand.get("fragment", ""))
    # NB: cand["current_sha"] (from the harvest bundle's manifest.json)
    # is intentionally NOT trusted here. We recompute the current SHA
    # from disk so a stale bundle (file edited after harvest) is
    # detected — re-stamping against a stale bundle SHA would mask the
    # subsequent edit as the new baseline.

    if not target_path or not feature_key or not marker:
        return (
            AcceptHarvestedEntry(
                target_path=target_path or "<unknown>",
                kind="block",
                action="error",
                reason="block candidate missing target_path / feature_key / marker",
            ),
            False,
        )

    key = MergeBlockCollector.key_for(target_path, feature_key, marker)
    entry_dict = merge_blocks.get(key)
    if entry_dict is None:
        return (
            AcceptHarvestedEntry(
                target_path=key,
                kind="block",
                action="error",
                reason=f"no merge_blocks entry in forge.toml for key {key!r}",
            ),
            False,
        )

    old_sha = str(entry_dict.get("sha256", ""))
    project_file = project_root / target_path
    if not project_file.is_file():
        return (
            AcceptHarvestedEntry(
                target_path=key,
                kind="block",
                action="error",
                reason=f"project file gone: {project_file}",
                old_sha=old_sha,
            ),
            False,
        )

    body = _read_block_body(project_file, feature_key, marker)
    if body is None:
        return (
            AcceptHarvestedEntry(
                target_path=key,
                kind="block",
                action="error",
                reason="sentinel block not found in project file",
                old_sha=old_sha,
            ),
            False,
        )

    current_sha = sha256_of_text(body)

    # Idempotent re-run: the manifest already reflects the user's body.
    # No write needed.
    if current_sha == old_sha:
        return (
            AcceptHarvestedEntry(
                target_path=key,
                kind="block",
                action="skipped-unchanged",
                reason="manifest already records this body",
                old_sha=old_sha,
                new_sha=current_sha,
            ),
            False,
        )

    # Has the upstream fragment actually been updated to match the
    # user's body? If we can resolve the fragment + its inject.yaml,
    # render the snippet against the project's options, and the
    # rendered upstream matches the user's body → the bundle has
    # landed. Otherwise we skip: the user's edit is still drift against
    # an unchanged upstream.
    upstream_snippet = _resolve_upstream_block_snippet(
        fragment_name=fragment_name,
        feature_key=feature_key,
        marker=marker,
        target_path=target_path,
        project_root=project_root,
    )
    if upstream_snippet is None:
        # No upstream available — can't verify the round-trip.
        # Conservative skip: the operator can re-run after the next
        # forge release, when the fragment registry hopefully knows
        # about the new snippet.
        return (
            AcceptHarvestedEntry(
                target_path=key,
                kind="block",
                action="skipped-not-applied",
                reason=(
                    f"cannot resolve upstream snippet for {fragment_name!r}; "
                    f"fragment may not yet ship the harvested edit"
                ),
                old_sha=old_sha,
                new_sha=current_sha,
            ),
            False,
        )

    upstream_sha = sha256_of_text(upstream_snippet)
    if upstream_sha != current_sha:
        # Upstream still emits the pre-edit body (or a different post-edit
        # body — partial landing). Either way, the round-trip isn't
        # complete; don't re-stamp.
        return (
            AcceptHarvestedEntry(
                target_path=key,
                kind="block",
                action="skipped-not-applied",
                reason=(
                    "upstream fragment snippet does not match the user's body; "
                    "the harvest bundle has not yet landed upstream"
                ),
                old_sha=old_sha,
                new_sha=current_sha,
            ),
            False,
        )

    # All three SHAs in agreement — the harvest landed AND the bundle's
    # recorded current_sha matches what's on disk. Re-stamp.
    new_entry = dict(entry_dict)
    new_entry["sha256"] = current_sha
    # Bump the fragment_version field if the registry knows about a new
    # version. The registry tracks per-implementation versions; we take
    # the first impl's version when available.
    new_version = _resolve_fragment_version(fragment_name)
    if new_version is not None:
        new_entry["fragment_version"] = new_version
    merge_blocks[key] = new_entry

    return (
        AcceptHarvestedEntry(
            target_path=key,
            kind="block",
            action="restamped-baseline",
            old_sha=old_sha,
            new_sha=current_sha,
            reason=(f"fragment_version → {new_version}" if new_version is not None else ""),
        ),
        True,
    )


def _accept_files(
    cand: Mapping[str, Any],
    *,
    project_root: Path,
    provenance: dict[str, dict[str, Any]],
) -> tuple[AcceptHarvestedEntry, bool]:
    """Re-stamp the manifest's ``provenance`` entry for a files candidate.

    Re-computes the project file's SHA. Compares against the
    fragment-shipped file's SHA (resolved via the registry). When they
    match (round-trip complete), updates ``provenance[rel]['sha256']``
    and bumps ``fragment_version``. Otherwise ``skipped-not-applied``.

    Returns ``(entry, changed)`` — see :func:`_accept_block`.
    """
    # The harvest bundle records the project-root-relative path under
    # ``target_path`` for files candidates (CandidatePatch.target_path is
    # the absolute path on disk; rel_path is the fragment-relative).
    # The manifest's [forge.provenance] keys are project-root-relative.
    # We derive the manifest key by stripping ``project_root`` off the
    # candidate's absolute target_path.
    target_path_str = str(cand.get("target_path", ""))
    fragment_name = str(cand.get("fragment", ""))
    rel_path = str(cand.get("rel_path", ""))

    if not target_path_str:
        return (
            AcceptHarvestedEntry(
                target_path=rel_path or "<unknown>",
                kind="files",
                action="error",
                reason="files candidate missing target_path",
            ),
            False,
        )

    project_file = Path(target_path_str)
    if not project_file.is_absolute():
        project_file = project_root / project_file

    try:
        manifest_key = project_file.resolve().relative_to(project_root).as_posix()
    except ValueError:
        return (
            AcceptHarvestedEntry(
                target_path=target_path_str,
                kind="files",
                action="error",
                reason=f"target_path {target_path_str!r} is outside project_root {project_root}",
            ),
            False,
        )

    entry_dict = provenance.get(manifest_key)
    if entry_dict is None:
        return (
            AcceptHarvestedEntry(
                target_path=manifest_key,
                kind="files",
                action="error",
                reason=f"no provenance entry in forge.toml for {manifest_key!r}",
            ),
            False,
        )

    old_sha = str(entry_dict.get("sha256", ""))
    if not project_file.is_file():
        return (
            AcceptHarvestedEntry(
                target_path=manifest_key,
                kind="files",
                action="error",
                reason=f"project file gone: {project_file}",
                old_sha=old_sha,
            ),
            False,
        )

    current_sha = sha256_of_file(project_file)
    if current_sha == old_sha:
        return (
            AcceptHarvestedEntry(
                target_path=manifest_key,
                kind="files",
                action="skipped-unchanged",
                reason="manifest already records this file",
                old_sha=old_sha,
                new_sha=current_sha,
            ),
            False,
        )

    # Has the upstream fragment file caught up to the user's edit?
    upstream_sha = _resolve_upstream_file_sha(
        fragment_name=fragment_name,
        rel_path=rel_path,
    )
    if upstream_sha is None:
        return (
            AcceptHarvestedEntry(
                target_path=manifest_key,
                kind="files",
                action="skipped-not-applied",
                reason=(
                    f"cannot resolve upstream file for {fragment_name!r}; "
                    f"fragment may not yet ship the harvested edit"
                ),
                old_sha=old_sha,
                new_sha=current_sha,
            ),
            False,
        )

    if upstream_sha != current_sha:
        return (
            AcceptHarvestedEntry(
                target_path=manifest_key,
                kind="files",
                action="skipped-not-applied",
                reason=(
                    "upstream fragment file does not match the user's edit; "
                    "the harvest bundle has not yet landed upstream"
                ),
                old_sha=old_sha,
                new_sha=current_sha,
            ),
            False,
        )

    # Round-trip complete: re-stamp.
    new_entry = dict(entry_dict)
    new_entry["sha256"] = current_sha
    new_version = _resolve_fragment_version(fragment_name)
    if new_version is not None:
        new_entry["fragment_version"] = new_version
    provenance[manifest_key] = new_entry

    return (
        AcceptHarvestedEntry(
            target_path=manifest_key,
            kind="files",
            action="restamped-baseline",
            old_sha=old_sha,
            new_sha=current_sha,
            reason=(f"fragment_version → {new_version}" if new_version is not None else ""),
        ),
        True,
    )


def _accept_new_file(
    cand: Mapping[str, Any],
    *,
    project_root: Path,
    provenance: dict[str, dict[str, Any]],
) -> tuple[AcceptHarvestedEntry, bool]:
    """Add a provenance entry for a brand-new file the user contributed.

    A ``new-file`` candidate represents a file the user added that the
    fragment didn't previously ship. After upstream picks it up, the
    project's manifest should record a provenance entry marking the
    fragment as the file's emitter, so a subsequent
    ``forge --verify`` doesn't flag it as untracked drift.

    Behavioural symmetry with :func:`_accept_files`: we still verify
    the upstream fragment now ships the file (round-trip complete)
    before mutating the manifest.
    """
    target_path_str = str(cand.get("target_path", ""))
    fragment_name = str(cand.get("fragment", ""))
    rel_path = str(cand.get("rel_path", ""))

    if not target_path_str:
        return (
            AcceptHarvestedEntry(
                target_path=rel_path or "<unknown>",
                kind="new-file",
                action="error",
                reason="new-file candidate missing target_path",
            ),
            False,
        )

    project_file = Path(target_path_str)
    if not project_file.is_absolute():
        project_file = project_root / project_file

    try:
        manifest_key = project_file.resolve().relative_to(project_root).as_posix()
    except ValueError:
        return (
            AcceptHarvestedEntry(
                target_path=target_path_str,
                kind="new-file",
                action="error",
                reason=f"target_path outside project_root {project_root}",
            ),
            False,
        )

    if not project_file.is_file():
        return (
            AcceptHarvestedEntry(
                target_path=manifest_key,
                kind="new-file",
                action="error",
                reason=f"project file gone: {project_file}",
            ),
            False,
        )

    current_sha = sha256_of_file(project_file)
    existing = provenance.get(manifest_key)
    if existing is not None and str(existing.get("sha256", "")) == current_sha:
        return (
            AcceptHarvestedEntry(
                target_path=manifest_key,
                kind="new-file",
                action="skipped-unchanged",
                reason="manifest already records this file",
                new_sha=current_sha,
                old_sha=str(existing.get("sha256", "")),
            ),
            False,
        )

    upstream_sha = _resolve_upstream_file_sha(
        fragment_name=fragment_name,
        rel_path=rel_path,
    )
    if upstream_sha is None or upstream_sha != current_sha:
        return (
            AcceptHarvestedEntry(
                target_path=manifest_key,
                kind="new-file",
                action="skipped-not-applied",
                reason=(f"upstream fragment {fragment_name!r} does not yet ship this file"),
                new_sha=current_sha,
                old_sha=str(existing.get("sha256", "")) if existing else "",
            ),
            False,
        )

    new_version = _resolve_fragment_version(fragment_name)
    new_entry: dict[str, Any] = {
        "origin": "fragment",
        "sha256": current_sha,
        "fragment_name": fragment_name,
    }
    if new_version is not None:
        new_entry["fragment_version"] = new_version
    provenance[manifest_key] = new_entry
    return (
        AcceptHarvestedEntry(
            target_path=manifest_key,
            kind="new-file",
            action="restamped-baseline",
            new_sha=current_sha,
            old_sha=str(existing.get("sha256", "")) if existing else "",
            reason="new provenance entry created",
        ),
        True,
    )


# ---------------------------------------------------------------------------
# Fragment-side resolution helpers
# ---------------------------------------------------------------------------


def _resolve_upstream_block_snippet(
    *,
    fragment_name: str,
    feature_key: str,
    marker: str,
    target_path: str,
    project_root: Path,
) -> str | None:
    """Render the upstream fragment's inject.yaml entry matching this block.

    Walks the fragment's implementations, loads each one's
    ``inject.yaml``, and renders the snippet matching ``(target, marker)``
    against the project's option values. Returns the rendered snippet,
    or ``None`` when the fragment / impl / inject.yaml / matching entry
    isn't reachable. ``None`` is the conservative signal — the caller
    interprets it as "bundle not yet landed" rather than re-stamping
    against an empty body.

    Mirrors the strategy :mod:`forge.sync.project_to_forge.harvester`'s
    ``_load_upstream_snippets`` uses, but constrained to one specific
    ``(target, marker, feature_key)`` triple so we don't waste work
    on irrelevant entries.
    """
    fragment = FRAGMENT_REGISTRY.get(fragment_name)
    if fragment is None:
        return None
    if not fragment.implementations:
        return None

    # Read the project's options so render-conditional snippets see the
    # same option values the forward applier did. Best-effort: missing
    # forge.toml just falls back to empty options.
    options: Mapping[str, Any] = {}
    try:
        data = read_forge_toml(project_root / "forge.toml")
        options = data.options
    except (FileNotFoundError, ValueError):
        pass

    try:
        from forge.appliers.plan import _load_injections
        from forge.fragments import _resolve_fragment_dir
    except ImportError:
        return None

    # The harvester re-bases the manifest's project-root-relative
    # target_path against the backend dir. We do the inverse: try each
    # impl's inject.yaml and accept any entry whose target matches the
    # last N segments of ``target_path`` (backend-relative). This handles
    # both project-scope and backend-scope fragments without needing the
    # candidate to carry the backend label.
    for impl in fragment.implementations.values():
        try:
            fragment_dir = _resolve_fragment_dir(impl.fragment_dir)
        except Exception:  # noqa: BLE001
            continue
        inject_yaml = fragment_dir / "inject.yaml"
        if not inject_yaml.is_file():
            continue
        try:
            records = _load_injections(inject_yaml, feature_key, options=dict(options))
        except Exception:  # noqa: BLE001
            continue
        for rec in records:
            # Match marker. The marker in the inject.yaml is the bare
            # form (e.g. ``MIDDLEWARE_REGISTRATION``); the manifest /
            # candidate carries the prefixed form (``FORGE:MIDDLEWARE_REGISTRATION``).
            # MergeBlockCollector.parse_key restored the prefix, so we
            # compare both.
            rec_marker = str(rec.marker)
            if rec_marker == marker:
                return str(rec.snippet)
            if f"FORGE:{rec_marker}" == marker:
                return str(rec.snippet)
            if rec_marker == marker.removeprefix("FORGE:"):
                return str(rec.snippet)
        # Also try the wildcard ``"<harvest>"`` feature_key — matches the
        # placeholder the harvester uses when the candidate's feature_key
        # differs from the fragment's owner key.
        try:
            records = _load_injections(inject_yaml, "<harvest>", options=dict(options))
        except Exception:  # noqa: BLE001
            continue
        for rec in records:
            rec_marker = str(rec.marker)
            marker_matches = rec_marker == marker or rec_marker == marker.removeprefix("FORGE:")
            # Best-effort: target relpath should also match the
            # candidate's last segments. If the fragment changed
            # which target file it injects into, the bundle is stale
            # and the caller's ``skipped-not-applied`` path is the
            # right call.
            if marker_matches and _matches_target_tail(str(rec.target), target_path):
                return str(rec.snippet)
    return None


def _matches_target_tail(impl_target: str, manifest_target: str) -> bool:
    """Lax target-equality check for inject.yaml lookup.

    The harvester re-bases the manifest's project-root-relative path
    against the backend directory before stamping it on
    ``_Injection.target``; we do the inverse here. Accepts a match when
    the inject.yaml's ``target`` is a tail-suffix of the manifest's
    full path. Tail comparison on POSIX-normalised paths.
    """
    impl_norm = impl_target.replace("\\", "/").lstrip("/")
    manifest_norm = manifest_target.replace("\\", "/").lstrip("/")
    return manifest_norm.endswith(impl_norm) or impl_norm == manifest_norm


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
