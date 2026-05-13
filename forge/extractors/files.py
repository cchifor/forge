"""FileExtractor — reverse counterpart of :mod:`forge.appliers.files`.

Where :class:`forge.appliers.files.FragmentFileApplier` copies a
fragment's ``files/`` tree into the target, this extractor walks the
same set of paths and looks for evidence of user edits relative to the
fragment baseline recorded in ``forge.toml``.

Phase 4 will implement file-level harvest using
:func:`forge.merge.reverse_file_three_way_decide` — for each
``(fragment_relpath, dst_relpath)`` pair in
:attr:`~forge.extractors.plan.ExtractionPlan.files`, hash the on-disk
file and compare against the manifest's last-applied SHA. Edits emit a
:class:`~forge.extractors.pipeline.CandidatePatch` of kind ``"files"``
(modify) or ``"new-file"`` (added without a baseline anchor).

Phase 3 ships the class as a stub so the
:class:`~forge.extractors.pipeline.ExtractorPipeline` contract is wired
but every call returns ``[]``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from forge.extractors.pipeline import CandidatePatch
    from forge.extractors.plan import ExtractionPlan
    from forge.fragment_context import FragmentContext


class FileExtractor:
    """Harvest user edits to fragment-shipped files. Stub in Phase 3."""

    kind = "files"

    def extract(
        self,
        ctx: FragmentContext,
        plan: ExtractionPlan,
    ) -> list[CandidatePatch]:
        """Return harvested candidates for ``plan.files``.

        Phase 4: walk ``plan.files``, hash each ``dst_relpath`` against
        ``ctx.file_baselines``, and emit one
        :class:`~forge.extractors.pipeline.CandidatePatch` per file that
        diverges. The risk classification is driven by
        :func:`forge.merge.reverse_file_three_way_decide`.

        Phase 3 returns an empty list — the pipeline contract is wired
        and the extractor is registered, but no harvest runs yet.
        """
        return []
