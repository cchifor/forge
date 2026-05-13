"""EnvExtractor — reverse counterpart of :mod:`forge.appliers.env`.

Where :class:`forge.appliers.env.FragmentEnvApplier` appends
``KEY=VALUE`` lines to ``<backend_dir>/.env.example``, this extractor
reads that file and harvests user edits to the values fragments
previously emitted.

Phase 4 will implement env-level harvest by comparing each
``(key, value)`` pair in
:attr:`~forge.extractors.plan.ExtractionPlan.env_vars` against the
current ``.env.example`` line. Edits emit a
:class:`~forge.extractors.pipeline.CandidatePatch` of kind ``"env"``.

Most env edits are "operator tuned the placeholder default" rather
than secrets — the harvester is intentionally conservative:

* Value-only change with matching key → ``"safe-apply"``.
* Key renamed or removed → ``"needs-review"`` (could be a fragment
  rename or a deliberate operator decision).
* Comments / surrounding lines reformatted → ``"needs-review"``.

Phase 3 ships the class as a stub returning ``[]``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from forge.extractors.pipeline import CandidatePatch
    from forge.extractors.plan import ExtractionPlan
    from forge.fragment_context import FragmentContext


class EnvExtractor:
    """Harvest ``.env.example`` value drift. Stub in Phase 3."""

    kind = "env"

    def extract(
        self,
        ctx: FragmentContext,
        plan: ExtractionPlan,
    ) -> list[CandidatePatch]:
        """Return harvested candidates for ``plan.env_vars``.

        Phase 4: open ``ctx.backend_dir / ".env.example"``, diff each
        declared ``(key, value)`` pair against the file, and emit a
        :class:`~forge.extractors.pipeline.CandidatePatch` per drift.

        Phase 3 returns an empty list — the pipeline contract is wired
        but no harvest runs yet.
        """
        return []
