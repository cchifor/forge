"""DepsExtractor — reverse counterpart of :mod:`forge.appliers.deps`.

Where :class:`forge.appliers.deps.FragmentDepsApplier` merges
fragment-declared dependency strings into ``pyproject.toml`` /
``package.json`` / ``Cargo.toml``, this extractor reads those same
manifests and harvests:

* User-pinned versions that drift from the fragment-declared spec
  (e.g. fragment says ``slowapi>=0.1.9``, manifest says
  ``slowapi==0.1.11``).
* Removed deps — fragment-declared but no longer present.
* Added deps — present in the manifest but not in any fragment plan,
  signalling the operator added a hand-rolled dependency that may
  belong upstream.

Phase 4 will implement dep-level harvest using
:func:`forge.merge.reverse_three_way_decide` over per-dep canonical
strings. The risk classification reflects the comparatively low
ambiguity of dependency-line diffs:

* Single-line version pin change → ``"safe-apply"``.
* Spec-form change (shorthand → table form for Cargo, scope rewrites
  for npm) → ``"needs-review"``.
* Conflicting upstream+local edits to the same dep → ``"conflict"``.

Phase 3 ships the class as a stub returning ``[]``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from forge.extractors.pipeline import CandidatePatch
    from forge.extractors.plan import ExtractionPlan
    from forge.fragment_context import FragmentContext


class DepsExtractor:
    """Harvest dependency drift from package manifests. Stub in Phase 3."""

    kind = "deps"

    def extract(
        self,
        ctx: FragmentContext,
        plan: ExtractionPlan,
    ) -> list[CandidatePatch]:
        """Return harvested candidates for ``plan.dependencies``.

        Phase 4: open the per-language manifest under ``ctx.backend_dir``,
        diff each declared dep against the manifest entry, and emit a
        :class:`~forge.extractors.pipeline.CandidatePatch` per drift.

        Phase 3 returns an empty list — the pipeline contract is wired
        but no harvest runs yet.
        """
        return []
