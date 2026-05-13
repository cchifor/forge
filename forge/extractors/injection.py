"""InjectionExtractor — reverse counterpart of :mod:`forge.appliers.injection`.

Where :class:`forge.appliers.injection.FragmentInjectionApplier` writes
fragment-rendered snippets between BEGIN/END sentinels in target files,
this extractor reads those same regions and harvests user edits.

Phase 4 will implement block-level harvest using
:func:`forge.merge.reverse_three_way_decide` — for each ``_Injection``
in :attr:`~forge.extractors.plan.ExtractionPlan.injections`, locate the
sentinel block in the project target, hash its body, and compare
against the fragment-rendered body the forward applier last emitted.
Edits emit a :class:`~forge.extractors.pipeline.CandidatePatch` of
kind ``"block"``.

The trickier classification cases live here:

* Multi-line block edits — even pure-literal — are flagged
  ``"needs-review"`` because the upstream fragment may have an
  intentional ordering or comment style the harvester shouldn't
  paper over.
* Edits inside Jinja interpolation are auto-flagged
  ``"needs-review"`` because the upstream template is rendered, not
  the literal text; the harvester can't safely propose a back-port
  without operator judgement.
* Missing sentinel pair — when forward provenance says a block was
  applied but the project no longer contains the markers — emits
  ``"conflict"``: the user (or another tool) stripped the markers
  and the extractor cannot anchor.

Phase 3 ships the class as a stub returning ``[]``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from forge.extractors.pipeline import CandidatePatch
    from forge.extractors.plan import ExtractionPlan
    from forge.fragment_context import FragmentContext


class InjectionExtractor:
    """Harvest user edits to fragment-injected blocks. Stub in Phase 3."""

    kind = "block"

    def extract(
        self,
        ctx: FragmentContext,
        plan: ExtractionPlan,
    ) -> list[CandidatePatch]:
        """Return harvested candidates for ``plan.injections``.

        Phase 4: for each injection record, locate its BEGIN/END
        sentinels in ``ctx.backend_dir / inj.target``, hash the block
        body, compare against the manifest baseline, and emit a
        :class:`~forge.extractors.pipeline.CandidatePatch` per
        divergent block.

        Phase 3 returns an empty list — the pipeline contract is wired
        but no harvest runs yet.
        """
        return []
