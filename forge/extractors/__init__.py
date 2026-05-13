"""Fragment extractors — symmetric counterpart of :mod:`forge.appliers`.

Where an applier *forward-applies* fragment intent into a generated
project (copy files, run injections, add deps, append env vars), an
extractor *reverse-extracts* user edits from a generated project as
candidate fragment patches.

Phase 3 of the bidirectional-sync plan (see
``.claude/plans/happy-inventing-eclipse.md``) lands the framework
scaffolding:

* :class:`ExtractionPlan` — the typed record of what a fragment will
  extract from, mirroring :class:`forge.appliers.plan.FragmentPlan`.
* :class:`CandidatePatch` — the per-edit harvest output. The Phase 4
  harvester collects patches into a bundle for review.
* :class:`ExtractorProtocol` — the contract every concrete extractor
  satisfies.
* :class:`ExtractorPipeline` — composes per-kind extractors into a
  single pass over a plan, aggregating their candidates.
* :class:`FileExtractor` / :class:`InjectionExtractor` /
  :class:`DepsExtractor` / :class:`EnvExtractor` — the four built-in
  extractors. Phase 3 ships them as stubs returning ``[]``; Phase 4
  fills them in against
  :func:`forge.merge.reverse_three_way_decide` and friends.

Third-party plugins that ship custom appliers should ship paired
extractors so their fragments survive round-trip (Phase 4
``forge --harvest``). The plugin facade exposes
:meth:`forge.api.ForgeAPI.add_extractor` for that hook-up.
"""

from __future__ import annotations

from forge.extractors.deps import DepsExtractor
from forge.extractors.env import EnvExtractor
from forge.extractors.files import FileExtractor
from forge.extractors.injection import InjectionExtractor
from forge.extractors.pipeline import (
    CandidatePatch,
    ExtractorPipeline,
    ExtractorProtocol,
)
from forge.extractors.plan import ExtractionPlan

__all__ = [
    "CandidatePatch",
    "DepsExtractor",
    "EnvExtractor",
    "ExtractionPlan",
    "ExtractorPipeline",
    "ExtractorProtocol",
    "FileExtractor",
    "InjectionExtractor",
]
