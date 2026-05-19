"""Structural (three-way-merge) ``kind="files"`` apply handler.

Split out from the original ``apply_bundle.py`` god module — see
:mod:`forge.sync.project_to_forge.apply_bundle` for the public surface.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from forge.fragments import FRAGMENT_REGISTRY
from forge.sync.project_to_forge.apply_bundle._dispatch import ApplyBundleEntry
from forge.sync.project_to_forge.apply_bundle._shared import (
    _resolve_fragment_dir_under,
    _resolve_impl_for_candidate,
)

if TYPE_CHECKING:
    from forge.extractors.pipeline import CandidatePatch


def _apply_files_structural_candidate(
    cand: CandidatePatch,
    *,
    forge_repo: Path,
    quiet: bool,
) -> ApplyBundleEntry:
    """Apply a structural (three-way-merge) ``kind="files"`` candidate.

    Invariant on entry: ``cand.risk == "conflict"`` — both the user and
    the upstream fragment moved divergently from the recorded baseline.
    A wholesale replace (as :func:`_apply_files_literal_candidate` would
    perform) would clobber the upstream change.

    Strategy:

    1. Resolve the fragment dir + target path the same way the literal
       handler does. Read the upstream body from the fragment tree
       BEFORE writing — that's the content the literal path would have
       overwritten.
    2. Write the user's current body into the fragment tree (so the
       user's edits land — they are the operator's primary concern).
    3. Emit a ``<target>.forge-merge`` sidecar via
       :func:`forge.sync.merge.write_file_sidecar` carrying the
       upstream-emitted body. The sidecar's existence is the signal
       to the maintainer that two changes need reconciling; ``git
       diff`` between target and sidecar shows the upstream delta the
       user's apply would otherwise have silently overwritten.

    Why not a proper three-way text merge? Three-way merge needs the
    BASELINE content, but :attr:`CandidatePatch.baseline_sha` is a hash,
    not the content — we cannot recover the bytes from the hash alone
    (no content-addressable store under ``forge/``). Writing both
    versions to disk and letting the operator reconcile is the honest
    fallback: nothing silently lost, the conflict is surfaced where the
    operator looks (the fragment tree itself).

    Returns ``status="applied"`` with the sidecar path embedded in
    ``ApplyBundleEntry.error`` so the report's ``errored`` count stays
    at zero while still flagging the entry to reviewers.
    """
    fragment = FRAGMENT_REGISTRY.get(cand.fragment)
    if fragment is None:
        return ApplyBundleEntry(
            fragment=cand.fragment,
            kind=cand.kind,
            rel_path=cand.rel_path,
            status="errored",
            error=f"fragment {cand.fragment!r} not in registry",
        )

    impl = _resolve_impl_for_candidate(fragment, cand)
    if impl is None:
        return ApplyBundleEntry(
            fragment=cand.fragment,
            kind=cand.kind,
            rel_path=cand.rel_path,
            status="errored",
            error=f"fragment {cand.fragment!r} has no implementation for backend {cand.backend!r}",
        )

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

    # Capture the upstream body BEFORE writing. If the fragment doesn't
    # ship this file (would be unusual for a conflict — the extractor
    # only emits one when upstream moved off baseline, implying the
    # fragment file exists) we still emit the user's content but with a
    # minimal sidecar carrying empty bytes so the conflict is visible.
    upstream_bytes: bytes = b""
    if target.is_file():
        try:
            upstream_bytes = target.read_bytes()
        except OSError:
            upstream_bytes = b""

    try:
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

    # Emit the sidecar via the shared :mod:`forge.sync.merge` primitive
    # so the on-disk shape matches what the forward applier's conflict
    # path produces — operators see one convention everywhere.
    from forge.sync.merge import write_file_sidecar  # noqa: PLC0415

    try:
        upstream_payload: str | bytes
        try:
            upstream_payload = upstream_bytes.decode("utf-8")
        except UnicodeDecodeError:
            upstream_payload = upstream_bytes
        sidecar_path = write_file_sidecar(
            target,
            upstream_payload,
            tag=f"apply-bundle:{cand.fragment}/{cand.rel_path}",
        )
    except OSError as e:
        # Failing to emit the sidecar still leaves the user's edit on
        # disk; surface as errored so the operator knows the conflict
        # wasn't fully recorded.
        return ApplyBundleEntry(
            fragment=cand.fragment,
            kind=cand.kind,
            rel_path=cand.rel_path,
            status="errored",
            target=str(target),
            error=f"sidecar write failed: {e}",
        )

    if not quiet:
        print(
            f"  [apply-bundle] {cand.fragment}/{cand.rel_path} → {target} "
            f"(conflict; sidecar={sidecar_path.name})"
        )

    return ApplyBundleEntry(
        fragment=cand.fragment,
        kind=cand.kind,
        rel_path=cand.rel_path,
        status="applied",
        target=str(target),
        error=f"structural conflict; upstream preserved in sidecar: {sidecar_path}",
    )
