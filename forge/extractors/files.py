"""FileExtractor — reverse counterpart of :mod:`forge.appliers.files`.

Where :class:`forge.appliers.files.FragmentFileApplier` copies a
fragment's ``files/`` tree into the target, this extractor walks the
same set of paths and looks for evidence of user edits relative to the
fragment baseline recorded in ``forge.toml``.

Phase 4 implements file-level harvest using
:func:`forge.sync.merge.reverse_file_three_way_decide`. For each
``(fragment_relpath, dst_relpath)`` pair in
:attr:`~forge.extractors.plan.ExtractionPlan.files`, the extractor hashes
the on-disk file and compares against the manifest's last-applied SHA.
Divergent files emit a
:class:`~forge.extractors.pipeline.CandidatePatch` of kind ``"files"``
carrying a unified diff in upstream→current direction. Binary files
emit a placeholder-diff candidate flagged ``"needs-review"`` because
the harvest review surface cannot meaningfully render a binary patch.
"""

from __future__ import annotations

import difflib
from typing import TYPE_CHECKING

from forge.extractors.pipeline import CandidatePatch, CandidateRisk, ExtractorKind
from forge.fragments import FRAGMENT_REGISTRY
from forge.sync.merge import (
    is_binary_file,
    reverse_file_three_way_decide,
    sha256_of_file,
)

if TYPE_CHECKING:
    from pathlib import Path

    from forge.extractors.plan import ExtractionPlan
    from forge.fragment_context import FragmentContext


class FileExtractor:
    """Harvest user edits to fragment-shipped files."""

    kind: ExtractorKind = "files"

    def extract(
        self,
        ctx: FragmentContext,
        plan: ExtractionPlan,
    ) -> list[CandidatePatch]:
        """Return harvested candidates for ``plan.files``.

        For each ``(fragment_relpath, dst_relpath)`` pair, the extractor:

        1. Resolves the upstream fragment file under the fragment's
           ``files/`` tree (via the registry lookup for
           ``plan.fragment_name``).
        2. Hashes the on-disk file at ``ctx.backend_dir / dst_relpath``.
        3. Reads the baseline SHA recorded in ``ctx.file_baselines``
           (POSIX rel-path keyed at ``project_root``).
        4. Runs :func:`forge.sync.merge.reverse_file_three_way_decide`
           to classify the divergence.

        Maps the symmetric decision to candidate-patch risk:

        * ``"safe-apply"`` → emit ``risk="safe-apply"`` with a unified
          diff from upstream→current.
        * ``"conflict"`` → emit ``risk="conflict"`` with the same diff.
        * ``"skipped-*"`` / ``"no-baseline"`` → emit nothing.

        Binary files take a special path: any divergence is flagged
        ``risk="needs-review"`` with a ``"<binary file changed>"``
        placeholder diff. Reviewers inspect the project file directly.
        """
        if not plan.files:
            return []

        fragment_files_dir = _fragment_files_dir(ctx, plan.fragment_name)
        if fragment_files_dir is None:
            return []

        candidates: list[CandidatePatch] = []
        for fragment_relpath, dst_relpath in plan.files:
            patch = self._extract_one(
                ctx=ctx,
                fragment_name=plan.fragment_name,
                fragment_files_dir=fragment_files_dir,
                fragment_relpath=fragment_relpath,
                dst_relpath=dst_relpath,
            )
            if patch is not None:
                candidates.append(patch)
        return candidates

    def _extract_one(
        self,
        *,
        ctx: FragmentContext,
        fragment_name: str,
        fragment_files_dir: Path,
        fragment_relpath: str,
        dst_relpath: str,
    ) -> CandidatePatch | None:
        fragment_file = fragment_files_dir / fragment_relpath
        project_file = ctx.backend_dir / dst_relpath

        # Upstream-side SHA — the fragment is the source of truth for
        # ``upstream_sha``. If the fragment file is gone, we have
        # nothing to compare against; skip silently. This is a packaging
        # bug at the fragment level, not a user edit.
        if not fragment_file.is_file():
            return None

        baseline_key = _baseline_key(
            project_file=project_file,
            project_root=ctx.project_root,
        )
        baseline_sha = ctx.file_baselines.get(baseline_key)

        current_sha: str | None = sha256_of_file(project_file) if project_file.is_file() else None
        upstream_sha = sha256_of_file(fragment_file)

        decision = reverse_file_three_way_decide(
            baseline_sha=baseline_sha,
            current_sha=current_sha,
            upstream_sha=upstream_sha,
        )

        if decision in ("skipped-idempotent", "skipped-no-change", "no-baseline"):
            return None

        # Binary files: cannot produce a meaningful unified diff. Surface
        # the candidate as needs-review with a placeholder so the
        # reviewer at least sees the path; the actual byte-level diff is
        # the reviewer's job (likely outside forge). ``current_body`` is
        # left empty for binary candidates — the apply-back path reads
        # ``target_path`` directly to preserve bytes.
        fragment_is_binary = is_binary_file(fragment_file)
        project_is_binary = project_file.is_file() and is_binary_file(project_file)
        if fragment_is_binary or project_is_binary:
            return CandidatePatch(
                fragment=fragment_name,
                backend=ctx.backend_config.name,
                kind="files",
                rel_path=fragment_relpath,
                target_path=str(project_file),
                diff="<binary file changed>",
                baseline_sha=baseline_sha,
                current_sha=current_sha or "",
                risk="needs-review",
                rationale="binary file diverges from fragment baseline",
                current_body="",
            )

        # Text path: render upstream→current unified diff. When the user
        # deleted the file, ``current`` is the empty document.
        upstream_text = fragment_file.read_text(encoding="utf-8")
        current_text = project_file.read_text(encoding="utf-8") if project_file.is_file() else ""

        diff = "".join(
            difflib.unified_diff(
                upstream_text.splitlines(keepends=True),
                current_text.splitlines(keepends=True),
                fromfile=f"a/{fragment_relpath}",
                tofile=f"b/{dst_relpath}",
            )
        )

        # Explicit CandidateRisk annotation — without it ty falls back
        # to ``str`` for the ternary because ``decision`` is itself a
        # broader str-typed value, and downstream callers lose the
        # Literal narrowing that Initiative #1 sub-task 2 introduced
        # on ``CandidatePatch.risk``.
        risk: CandidateRisk = "safe-apply" if decision == "safe-apply" else "conflict"
        rationale = (
            "user edited fragment file; upstream unchanged"
            if decision == "safe-apply"
            else "user and upstream both diverged from baseline"
        )
        return CandidatePatch(
            fragment=fragment_name,
            backend=ctx.backend_config.name,
            kind="files",
            rel_path=fragment_relpath,
            target_path=str(project_file),
            diff=diff,
            baseline_sha=baseline_sha,
            current_sha=current_sha or "",
            risk=risk,
            rationale=rationale,
            current_body=current_text,
        )


def _fragment_files_dir(ctx: FragmentContext, fragment_name: str) -> Path | None:
    """Resolve the fragment's ``files/`` directory for the active backend.

    Returns ``None`` when the fragment isn't registered, the backend
    language has no implementation, or the implementation ships no
    ``files/`` tree. Each ``None`` return collapses to "no candidates"
    at the call site — symmetric to the forward applier silently
    skipping fragments without a ``files_dir``.
    """
    # Lazy import to avoid the registry's startup-audit being hit on
    # extractor module load — same shape the appliers use.
    from forge.fragments import _resolve_fragment_dir  # noqa: PLC0415

    fragment = FRAGMENT_REGISTRY.get(fragment_name)
    if fragment is None:
        return None
    impl = fragment.implementations.get(ctx.backend_config.language)
    if impl is None:
        return None
    fragment_dir = _resolve_fragment_dir(impl.fragment_dir)
    files_dir = fragment_dir / "files"
    if not files_dir.is_dir():
        return None
    return files_dir


def _baseline_key(*, project_file: Path, project_root: Path) -> str:
    """POSIX rel-path key matching the forward applier's ``_rel_key``.

    The manifest stores baselines keyed by ``project_root``-relative
    POSIX paths; the extractor must mint the same key shape so the
    lookup hits.
    """
    try:
        return project_file.relative_to(project_root).as_posix()
    except ValueError:
        return project_file.as_posix()
