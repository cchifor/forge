"""Apply harvest-bundle candidates back to the forge fragment tree (Phase 5).

The forward direction (``forge --update`` →
:func:`forge.sync.forge_to_project.updater.update_project`) re-applies
fragment intent into a generated project. The reverse direction
(``forge --harvest`` →
:func:`forge.sync.project_to_forge.harvester.harvest_project`) extracts
user edits as candidate fragment patches. This module closes the loop:
given a :class:`HarvestBundle`, write the user edits back into the
fragment source tree so a subsequent ``forge --update`` (or a fresh
``forge --generate``) would re-emit the user's text.

Phase 5 scope — files-only support:
  * ``kind="files"`` → overwrite ``<fragment_dir>/<lang>/files/<rel>``
    with the candidate's current content.
  * ``kind="block"`` → DEFERRED (Phase 6). Rewriting inject.yaml
    snippets requires recovering ``current_body`` from the candidate;
    the harvester currently records only a unified diff. Plumbing
    ``current_body`` through :class:`CandidatePatch` is the obvious
    next step but is intentionally out-of-scope here so the round-trip
    CI gate ships before the apply-back surface is fully built out.
  * ``kind="deps"`` / ``kind="env"`` → DEFERRED. These need structural
    reasoning (which fragment.dependencies field gets the addition?
    where do option-conditional deps go?) that is best handled
    interactively rather than by an automated lane.

The contract is intentionally narrow: ``apply_bundle_to_fragments`` is
the substrate that ``forge --harvest --accept`` (a Phase 6 CLI verb)
will sit on top of, plus the dependency the round-trip CI lane uses to
exercise the full forward→reverse→apply→forward cycle in tests.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from forge.fragments import FRAGMENT_REGISTRY

if TYPE_CHECKING:
    from forge.extractors.pipeline import CandidatePatch
    from forge.fragments import Fragment, FragmentImplSpec
    from forge.sync.project_to_forge.harvester import HarvestBundle


# Risk classifications the bundle applier acts on by default. Mirrors
# the CLI's ``--accept-harvested`` default surface. Operators wanting
# to override this for a one-off review pass pass an explicit
# ``risk_filter`` to :func:`apply_bundle_to_fragments`.
_DEFAULT_RISK_FILTER: tuple[str, ...] = ("safe-apply",)


@dataclass(frozen=True)
class ApplyBundleEntry:
    """One candidate's resolution after running the apply step.

    Attributes:
        fragment: Fragment name (matches :attr:`CandidatePatch.fragment`).
        kind: Candidate kind (``"files"`` / ``"block"`` / ``"deps"`` /
            ``"env"``).
        rel_path: POSIX rel-path identifying the patch target inside the
            fragment tree (or the project tree, for ``"block"`` /
            ``"deps"`` / ``"env"``).
        status: One of ``"applied"`` (write succeeded), ``"skipped"``
            (filtered out by ``risk_filter``), ``"deferred"`` (kind not
            supported in v1 — see module docstring), or ``"errored"``
            (apply attempted but failed; see :attr:`error`).
        target: Absolute path on disk that was (or would have been)
            written. ``None`` for ``"skipped"`` / ``"deferred"`` /
            ``"errored"`` entries that didn't resolve a fragment path.
        error: Free-form error message for ``"errored"`` entries. Empty
            for the others.
    """

    fragment: str
    kind: str
    rel_path: str
    status: str
    target: str | None = None
    error: str = ""


@dataclass(frozen=True)
class ApplyBundleReport:
    """Aggregate report from a :func:`apply_bundle_to_fragments` run.

    Attributes:
        entries: Per-candidate disposition. Order matches the bundle's
            ``candidates`` list so reviewers can correlate entries
            against the harvest manifest.
        applied: Count of candidates the applier wrote successfully.
        skipped: Count of candidates filtered out by ``risk_filter`` or
            by candidate-level filters (binary files, sentinel-corrupt
            blocks).
        deferred: Count of candidates whose ``kind`` is not yet
            supported (``"block"``, ``"deps"``, ``"env"`` in v1).
        errored: Count of candidates the applier attempted to write but
            failed on (permission denied, missing fragment dir, etc.).
    """

    entries: list[ApplyBundleEntry] = field(default_factory=list)
    applied: int = 0
    skipped: int = 0
    deferred: int = 0
    errored: int = 0


def apply_bundle_to_fragments(
    bundle: HarvestBundle,
    forge_repo: Path,
    *,
    risk_filter: tuple[str, ...] = _DEFAULT_RISK_FILTER,
    quiet: bool = False,
) -> ApplyBundleReport:
    """Apply a harvest bundle's candidates back to the forge source tree.

    For each candidate with ``risk in risk_filter``:
      * ``kind="files"`` → overwrite the fragment-shipped file at
        ``<fragment_dir>/<lang>/files/<rel>`` with the candidate's
        current on-disk content (read from
        :attr:`CandidatePatch.target_path`). When the fragment doesn't
        ship a ``files/`` entry at that rel-path we still write it —
        the user-added file is now part of the fragment.
      * ``kind="block"`` → DEFERRED in v1. Emit a ``deferred`` entry
        and leave the fragment tree untouched. The CLI Phase 6 verb
        will wire snippet rewriting; until then the round-trip lane
        treats block-bearing scenarios as expected-fail.
      * ``kind="deps"`` / ``kind="env"`` → DEFERRED in v1. Same
        rationale; emit a ``deferred`` entry.

    Args:
        bundle: The harvest bundle to apply. Typically the result of a
            preceding :func:`harvest_project` call.
        forge_repo: Root of the forge source tree (the directory that
            contains ``forge/__init__.py``). The fragments under
            ``forge/templates/_fragments/`` and ``forge/features/`` are
            both honoured — the helper relies on the registry's
            ``impl.fragment_dir`` lookup to find the canonical location.
        risk_filter: Subset of the candidate-risk vocabulary the helper
            will act on. Defaults to ``("safe-apply",)`` — the
            auto-acceptable tier. Pass ``("safe-apply", "needs-review")``
            to land needs-review candidates as well (rare; the operator
            should know what they're doing).
        quiet: When ``False``, prints a one-line per-candidate progress
            note. Tests should pass ``True``.

    Returns:
        An :class:`ApplyBundleReport` with per-candidate dispositions
        and aggregate counts.

    The helper never raises on individual candidate failures — it
    records the error in the report and continues. The caller can
    inspect ``report.errored`` and the matching entries to decide how to
    surface the partial-failure case.
    """
    entries: list[ApplyBundleEntry] = []
    applied = 0
    skipped = 0
    deferred = 0
    errored = 0

    for cand in bundle.candidates:
        # Filter by risk. Skipped candidates are still recorded so the
        # report shows the reviewer "we saw this; here's why we didn't
        # apply it" — preferable to silent drop.
        if cand.risk not in risk_filter:
            entries.append(
                ApplyBundleEntry(
                    fragment=cand.fragment,
                    kind=cand.kind,
                    rel_path=cand.rel_path,
                    status="skipped",
                    error=f"risk={cand.risk!r} not in filter {risk_filter!r}",
                )
            )
            skipped += 1
            continue

        if cand.kind == "files":
            entry = _apply_files_candidate(cand, forge_repo=forge_repo, quiet=quiet)
        else:
            # block / deps / env — deferred to Phase 6. Surface a
            # ``deferred`` entry so the report makes the limitation
            # visible rather than silent.
            entry = ApplyBundleEntry(
                fragment=cand.fragment,
                kind=cand.kind,
                rel_path=cand.rel_path,
                status="deferred",
                error=f"kind={cand.kind!r} apply-back not implemented in v1 (Phase 6)",
            )

        entries.append(entry)
        if entry.status == "applied":
            applied += 1
        elif entry.status == "deferred":
            deferred += 1
        elif entry.status == "errored":
            errored += 1
        elif entry.status == "skipped":
            skipped += 1

    if not quiet:
        print(
            f"  [apply-bundle] applied={applied} skipped={skipped} "
            f"deferred={deferred} errored={errored}"
        )

    return ApplyBundleReport(
        entries=entries,
        applied=applied,
        skipped=skipped,
        deferred=deferred,
        errored=errored,
    )


# ---------------------------------------------------------------------------
# Per-kind appliers
# ---------------------------------------------------------------------------


def _apply_files_candidate(
    cand: CandidatePatch,
    *,
    forge_repo: Path,
    quiet: bool,
) -> ApplyBundleEntry:
    """Apply a ``kind="files"`` candidate to the fragment tree.

    Resolves the fragment's ``files/`` directory via the registry, then
    writes the candidate's current on-disk content (read from
    ``cand.target_path``) into ``<files_dir>/<cand.rel_path>``.

    Errors are captured as ``errored`` entries — the apply step is best-
    effort, never raising past the caller. Returns the disposition
    entry; the caller aggregates counts.
    """
    # Locate the fragment in the registry. A bundle whose fragments
    # aren't registered (plugin disabled, fragment removed) is a
    # config-time error — surface it but keep going.
    fragment = FRAGMENT_REGISTRY.get(cand.fragment)
    if fragment is None:
        return ApplyBundleEntry(
            fragment=cand.fragment,
            kind=cand.kind,
            rel_path=cand.rel_path,
            status="errored",
            error=f"fragment {cand.fragment!r} not in registry",
        )

    # The candidate carries a ``backend`` label (e.g. ``api``); the
    # registry indexes implementations by :class:`BackendLanguage`.
    # We don't have the language directly, so try every registered impl
    # and pick the one whose ``files_dir`` actually contains the
    # candidate's rel_path (or — for new fragment files — pick the
    # first impl that exists). This handles the multi-backend case
    # cleanly: a single fragment with python+node+rust implementations
    # picks the right one without requiring the bundle to record the
    # backend language explicitly.
    impl = _resolve_impl_for_candidate(fragment, cand)
    if impl is None:
        return ApplyBundleEntry(
            fragment=cand.fragment,
            kind=cand.kind,
            rel_path=cand.rel_path,
            status="errored",
            error=f"fragment {cand.fragment!r} has no implementation for backend {cand.backend!r}",
        )

    # Resolve the fragment dir against the supplied forge_repo so the
    # apply lands in the operator's chosen tree (typically a tmp_path
    # clone of the source so tests don't mutate the real fragments).
    fragment_dir = _resolve_fragment_dir_under(
        forge_repo=forge_repo,
        fragment_dir_str=impl.fragment_dir,
    )
    if fragment_dir is None or not fragment_dir.is_dir():
        return ApplyBundleEntry(
            fragment=cand.fragment,
            kind=cand.kind,
            rel_path=cand.rel_path,
            status="errored",
            error=f"fragment dir not found under forge_repo: {impl.fragment_dir}",
        )

    files_dir = fragment_dir / "files"
    target = files_dir / cand.rel_path

    # Read the current content from the project. ``target_path`` is
    # absolute (the harvester stamps it). If the file disappeared
    # between harvest and apply, surface as errored — the bundle is
    # stale.
    source = Path(cand.target_path)
    if not source.is_file():
        return ApplyBundleEntry(
            fragment=cand.fragment,
            kind=cand.kind,
            rel_path=cand.rel_path,
            status="errored",
            target=str(target),
            error=f"source file gone since harvest: {source}",
        )

    try:
        # ``read_bytes`` + ``write_bytes`` preserves the user's chosen
        # line endings. We deliberately don't normalize on write — the
        # next ``forge --generate`` re-emits the file, and any LF/CRLF
        # difference vs. the user's edit is exactly what the round-trip
        # contract should preserve.
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
    except OSError as e:
        return ApplyBundleEntry(
            fragment=cand.fragment,
            kind=cand.kind,
            rel_path=cand.rel_path,
            status="errored",
            target=str(target),
            error=f"write failed: {e}",
        )

    if not quiet:
        print(f"  [apply-bundle] {cand.fragment}/{cand.rel_path} → {target}")

    return ApplyBundleEntry(
        fragment=cand.fragment,
        kind=cand.kind,
        rel_path=cand.rel_path,
        status="applied",
        target=str(target),
    )


def _resolve_impl_for_candidate(
    fragment: Fragment, cand: CandidatePatch
) -> FragmentImplSpec | None:
    """Pick the fragment impl whose ``files/`` tree carries ``cand.rel_path``.

    The harvester records a ``backend`` label (``api`` / ``project``)
    on the candidate but not the underlying ``BackendLanguage``, so we
    can't index ``fragment.implementations`` directly. Instead, we
    enumerate the available impls and prefer one whose ``files/``
    subtree already contains the rel-path on disk. Failing that we
    fall back to the first registered impl — the user-added-file case.

    Returns the matching :class:`FragmentImplSpec`, or ``None`` when
    the fragment has no implementations registered.
    """
    impls = fragment.implementations
    if not impls:
        return None
    # First pass: prefer an impl whose files_dir already carries the
    # rel_path. That's the typical "fragment file the user edited" case.
    from forge.feature_injector import _resolve_fragment_dir  # noqa: PLC0415

    for impl in impls.values():
        try:
            fragment_dir = _resolve_fragment_dir(impl.fragment_dir)
        except Exception:  # noqa: BLE001 — registry-level path resolution glitch.
            continue
        if (fragment_dir / "files" / cand.rel_path).is_file():
            return impl
    # Fallback: take the first impl. New fragment file case — the
    # operator added a file the fragment didn't previously ship. We
    # land it on whatever impl is first registered.
    return next(iter(impls.values()))


def _resolve_fragment_dir_under(
    *,
    forge_repo: Path,
    fragment_dir_str: str,
) -> Path | None:
    """Resolve a fragment's directory relative to a user-supplied forge_repo.

    Mirrors :func:`forge.feature_injector._resolve_fragment_dir`, but
    re-roots the relative paths under ``forge_repo / forge / templates
    / _fragments`` so tests can point at a tmp_path clone of the source
    tree without mutating the real installed package.

    Absolute paths are honoured verbatim — same behaviour as the
    forward resolver. For tests that copy ``forge/`` to a tmp dir and
    pass that as ``forge_repo``, the relative-path case is the one
    that matters.
    """
    path = Path(fragment_dir_str)
    if path.is_absolute():
        # Plugin / absolute fragment dir — honour it verbatim. The
        # caller's forge_repo doesn't apply.
        return path

    # Built-in fragments live under either:
    #   forge/templates/_fragments/<fragment>
    #   forge/features/<area>/templates/<fragment>/<lang>/
    # The relative path stored on the impl spec is interpreted against
    # the templates/_fragments/ root for the first layout; for the
    # second layout it's an absolute path coming through the absolute
    # branch above. So the relative resolution is unambiguous.
    candidate = forge_repo / "forge" / "templates" / "_fragments" / fragment_dir_str
    if candidate.is_dir():
        return candidate

    # Fall through: try without the ``forge/`` prefix in case the
    # caller passed the inner ``forge`` package as forge_repo.
    candidate2 = forge_repo / "templates" / "_fragments" / fragment_dir_str
    if candidate2.is_dir():
        return candidate2

    return None
