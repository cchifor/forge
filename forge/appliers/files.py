"""Applier for a fragment's ``files/`` tree.

Copies every file under ``plan.files_dir`` into ``ctx.backend_dir``
preserving structure. Collision behaviour is driven by
:data:`forge.fragment_context.UpdateMode`:

* ``strict``    — fresh generation. Fragments may not overlap the base
                  template or each other; raise ``FRAGMENT_FILES_OVERLAP``
                  on any pre-existing destination.
* ``skip``      — pre-1.1 ``forge --update`` behaviour. Pre-existing
                  destinations are preserved unconditionally.
* ``overwrite`` — clobber pre-existing destinations regardless of user
                  edits. The escape hatch.
* ``merge``     — P0.1 (1.1.0-alpha.2). Three-way decide via
                  :func:`forge.merge.file_three_way_decide`; emit a
                  ``.forge-merge`` (or ``.forge-merge.bin``) sidecar on
                  conflict and continue. The user resolves by hand.

Epic A (1.1.0-alpha.1) lifted the body out of
``forge.feature_injector._copy_files`` into this module; the legacy
function name is re-exported there for one minor as a deprecation shim.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import TYPE_CHECKING

from forge.errors import FRAGMENT_FILES_OVERLAP, FragmentError
from forge.fragment_context import UpdateMode
from forge.merge import (
    FileMergeOutcome,
    file_three_way_decide,
    is_binary_file,
    sha256_of_file,
    write_file_sidecar,
)
from forge.provenance import ProvenanceCollector

if TYPE_CHECKING:
    from collections.abc import Mapping

    from forge.appliers.plan import FragmentPlan
    from forge.fragment_context import FragmentContext


class FragmentFileApplier:
    """Copies a fragment's ``files/`` tree into the target dir."""

    def apply(self, ctx: FragmentContext, plan: FragmentPlan) -> None:
        if plan.files_dir is None:
            return
        copy_files(
            plan.files_dir,
            ctx.backend_dir,
            update_mode=ctx.update_mode,
            file_baselines=ctx.file_baselines,
            collector=ctx.provenance,
            project_root=ctx.project_root,
            fragment_name=plan.feature_key,
        )


def copy_files(
    src: Path,
    dst_root: Path,
    *,
    update_mode: UpdateMode = "strict",
    file_baselines: Mapping[str, str] | None = None,
    collector: ProvenanceCollector | None = None,
    project_root: Path | None = None,
    fragment_name: str | None = None,
) -> tuple[FileMergeOutcome, ...]:
    """Copy every file under ``src/`` into ``dst_root/``, preserving structure.

    Returns the per-file outcomes for the run. Callers that need a
    conflict tally (the updater, plan-update preview) read the tuple;
    callers that don't care (fresh generation) discard it.

    See the module docstring for collision semantics per ``update_mode``.
    """
    baselines: Mapping[str, str] = file_baselines or {}
    outcomes: list[FileMergeOutcome] = []
    for src_path in src.rglob("*"):
        if not src_path.is_file():
            continue
        rel = src_path.relative_to(src)
        dst_path = dst_root / rel

        outcome = _apply_one_file(
            src_path=src_path,
            dst_path=dst_path,
            update_mode=update_mode,
            baselines=baselines,
            project_root=project_root,
            collector=collector,
            fragment_name=fragment_name,
        )
        outcomes.append(outcome)
    return tuple(outcomes)


def _apply_one_file(
    *,
    src_path: Path,
    dst_path: Path,
    update_mode: UpdateMode,
    baselines: Mapping[str, str],
    project_root: Path | None,
    collector: ProvenanceCollector | None,
    fragment_name: str | None,
) -> FileMergeOutcome:
    """Apply one source-file → destination decision.

    Pure dispatcher: figures out the action, then performs at most one
    of {write, sidecar, no-op}. Returns the outcome so the caller can
    aggregate.
    """
    if not dst_path.exists():
        # Fresh emit — same in every mode. No baseline lookup needed.
        _write(src_path, dst_path)
        _record(collector, dst_path, fragment_name)
        return FileMergeOutcome(action="applied", target=dst_path)

    # dst exists — collision policy.
    if update_mode == "strict":
        raise FragmentError(
            f"Fragment '{src_path.parent.parent.name}' tried to overwrite "
            f"existing file '{dst_path}'. Use inject.yaml to modify "
            "existing files; fragments/files/ is for new paths only.",
            code=FRAGMENT_FILES_OVERLAP,
            context={
                "fragment": src_path.parent.parent.name,
                "destination": str(dst_path),
            },
        )

    if update_mode == "skip":
        # Pre-1.1 semantics: preserve pre-existing destination silently.
        # We don't re-record provenance — the caller's collector should
        # carry the prior record forward (see updater seeding).
        return FileMergeOutcome(action="skipped-no-change", target=dst_path)

    if update_mode == "overwrite":
        _write(src_path, dst_path)
        _record(collector, dst_path, fragment_name)
        return FileMergeOutcome(action="applied", target=dst_path)

    # update_mode == "merge"
    return _apply_merge(
        src_path=src_path,
        dst_path=dst_path,
        baselines=baselines,
        project_root=project_root,
        collector=collector,
        fragment_name=fragment_name,
    )


def _apply_merge(
    *,
    src_path: Path,
    dst_path: Path,
    baselines: Mapping[str, str],
    project_root: Path | None,
    collector: ProvenanceCollector | None,
    fragment_name: str | None,
) -> FileMergeOutcome:
    """Three-way file-merge dispatch. ``dst_path`` is known to exist."""
    rel_key = _rel_key(dst_path, project_root)
    baseline_sha = baselines.get(rel_key)
    new_sha = sha256_of_file(src_path)
    current_sha = sha256_of_file(dst_path)

    decision = file_three_way_decide(
        baseline_sha=baseline_sha,
        current_sha=current_sha,
        new_sha=new_sha,
    )

    if decision == "applied":
        _write(src_path, dst_path)
        _record(collector, dst_path, fragment_name)
        return FileMergeOutcome(action="applied", target=dst_path)

    if decision == "skipped-idempotent":
        # File already matches what the fragment would write. Re-record
        # provenance so the manifest reflects that this content is
        # fragment-authored, even though we didn't physically write.
        _record(collector, dst_path, fragment_name)
        return FileMergeOutcome(action="skipped-idempotent", target=dst_path)

    if decision == "skipped-no-change":
        # Fragment unchanged; user has local edits. Preserve them. The
        # collector keeps the prior baseline record (caller seeded it).
        return FileMergeOutcome(action="skipped-no-change", target=dst_path)

    if decision == "no-baseline":
        # Pre-1.1 / untracked file. Preserve as user-authored.
        return FileMergeOutcome(action="no-baseline", target=dst_path)

    # decision == "conflict"
    tag = f"{fragment_name or 'fragment'}:{rel_key}"
    if is_binary_file(src_path):
        sidecar = write_file_sidecar(dst_path, src_path.read_bytes(), tag=tag)
    else:
        sidecar = write_file_sidecar(
            dst_path,
            src_path.read_text(encoding="utf-8"),
            tag=tag,
        )
    return FileMergeOutcome(action="conflict", target=dst_path, sidecar_path=sidecar)


def _write(src_path: Path, dst_path: Path) -> None:
    """Write ``src_path`` content to ``dst_path``, creating parents."""
    dst_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src_path, dst_path)


def _record(
    collector: ProvenanceCollector | None,
    dst_path: Path,
    fragment_name: str | None,
) -> None:
    """Record a fragment-origin provenance entry for ``dst_path``."""
    if collector is None:
        return
    collector.record(dst_path, origin="fragment", fragment_name=fragment_name)


def _rel_key(dst_path: Path, project_root: Path | None) -> str:
    """POSIX rel-path key for the file_baselines / provenance map."""
    if project_root is None:
        return dst_path.as_posix()
    try:
        return dst_path.relative_to(project_root).as_posix()
    except ValueError:
        return dst_path.as_posix()
