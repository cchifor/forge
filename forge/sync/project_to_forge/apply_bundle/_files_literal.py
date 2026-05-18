"""Literal (wholesale-replace) ``kind="files"`` apply handler.

Split out from the original ``apply_bundle.py`` god module — see
:mod:`forge.sync.project_to_forge.apply_bundle` for the public surface.

The dispatcher entry point :func:`_apply_files_candidate` lives here
because the literal path is the default; it delegates to
:func:`_apply_files_structural_candidate` when
:func:`_is_structural_files_candidate` is True.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from forge.fragments import FRAGMENT_REGISTRY
from forge.sync.project_to_forge.apply_bundle._dispatch import ApplyBundleEntry
from forge.sync.project_to_forge.apply_bundle._files_structural import (
    _apply_files_structural_candidate,
)
from forge.sync.project_to_forge.apply_bundle._shared import (
    _resolve_fragment_dir_under,
    _resolve_impl_for_candidate,
)

if TYPE_CHECKING:
    from forge.extractors.pipeline import CandidatePatch


def _apply_files_candidate(
    cand: CandidatePatch,
    *,
    forge_repo: Path,
    quiet: bool,
) -> ApplyBundleEntry:
    """Dispatch a ``kind="files"`` candidate to the literal or structural path.

    Split on :func:`_is_structural_files_candidate`:

    * ``False`` (literal, ``risk="safe-apply"`` or ``risk="needs-review"``)
      — wholesale replace via :func:`_apply_files_literal_candidate`. The
      file extractor only emits ``safe-apply`` when the fragment baseline
      equals the upstream body, so writing the user's text becomes the
      unambiguous new fragment content. ``needs-review`` (binary files,
      empty-baseline-with-existing-current) also takes this path because
      no three-way reconciliation is meaningful.
    * ``True`` (structural, ``risk="conflict"``) — three-way merge via
      :func:`_apply_files_structural_candidate`. Both the user and the
      upstream fragment moved relative to the recorded baseline, so a
      wholesale replace would clobber the upstream change. The structural
      handler writes the user's current text AND emits a
      ``<target>.forge-merge`` sidecar carrying the upstream-emitted
      content so the maintainer can manually reconcile.

    Errors are captured as ``errored`` entries — the apply step is best-
    effort, never raising past the caller. Returns the disposition
    entry; the caller aggregates counts.
    """
    if _is_structural_files_candidate(cand):
        return _apply_files_structural_candidate(cand, forge_repo=forge_repo, quiet=quiet)
    return _apply_files_literal_candidate(cand, forge_repo=forge_repo, quiet=quiet)


def _is_structural_files_candidate(cand: CandidatePatch) -> bool:
    """Return ``True`` when a ``kind="files"`` candidate needs three-way merge.

    Structural = both the user and the upstream fragment moved divergently
    from the recorded baseline. The file extractor emits this case with
    ``risk="conflict"`` (see
    :func:`forge.sync.merge.reverse_file_three_way_decide` and
    :class:`forge.extractors.files.FileExtractor`). All other risk values
    on a ``files`` candidate (``safe-apply``, ``needs-review``) take the
    literal wholesale-replace path because no meaningful three-way
    reconciliation exists for them.

    Pure over the candidate; no I/O. Callers that want to override the
    classification (e.g. force a literal apply on a conflict candidate)
    should mutate ``cand.risk`` before dispatching — the helper is the
    single source of truth so behavior stays consistent across call
    sites.
    """
    return cand.risk == "conflict"


def _apply_files_literal_candidate(
    cand: CandidatePatch,
    *,
    forge_repo: Path,
    quiet: bool,
) -> ApplyBundleEntry:
    """Apply a literal (wholesale-replace) ``kind="files"`` candidate.

    Resolves the fragment's ``files/`` directory via the registry, then
    writes the candidate's current on-disk content (read from
    ``cand.target_path``) into ``<files_dir>/<cand.rel_path>``.

    The pre-Phase-6 path — kept verbatim. The file extractor's
    ``safe-apply`` decision tells us the fragment baseline equals the
    upstream-emitted body, so writing the user's text is the
    unambiguous new fragment content. No merge needed.
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
