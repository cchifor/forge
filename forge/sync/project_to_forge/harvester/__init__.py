"""`forge --harvest` orchestrator (Phase 4, bidirectional sync).

Walks a generated project's ``forge.toml`` manifest, runs the
:class:`forge.extractors.ExtractorPipeline` for every fragment with
recorded provenance, and collects the candidate patches into a
:class:`HarvestBundle`. The CLI dispatcher (``forge --harvest``) calls
:func:`harvest_project` and either writes the bundle to disk or streams
it as JSON.

The orchestration is symmetric to the forward flow (apply):

* Forward (``forge --update`` →
  :func:`forge.sync.forge_to_project.updater.update_project`):
  resolver → :class:`FragmentPlan` per fragment → applier pipeline.
* Reverse (``forge --harvest`` → :func:`harvest_project`):
  manifest → :class:`ExtractionPlan` per fragment → extractor pipeline.

The asymmetry sits in plan construction. The forward plan resolves
fragment metadata against the registry to know *what to write*. The
reverse plan inverts that: it inspects what the forward direction
recorded in the manifest (``[forge.provenance]`` /
``[forge.merge_blocks]``) and uses that as the set of paths to inspect
on disk.

Phase 4 backbone:
  * file-level extraction is wired (the parallel agent owns the
    :class:`forge.extractors.files.FileExtractor` body);
  * block-level extraction is the headline contribution of this PR
    (:class:`forge.extractors.injection.InjectionExtractor`);
  * deps + env extraction surface ``needs-review`` candidates via the
    pair extractors the parallel agent wires up.

Out of scope for this PR (deferred to Phase 4b):
  * ``--emit-pr`` integration with ``gh pr create``.
  * ``--accept-harvested`` to land candidates back in the fragment tree.
  * ``--reapply-baseline`` to restamp baselines after a harvest cycle.

Interactive review (``--harvest-interactive``) is wired via the
:data:`PromptCallback` parameter on :func:`harvest_project`. Callers
inject a callback that prompts ``accept`` / ``skip`` / ``quit`` per
candidate; the default ``None`` preserves the headless contract
(every candidate is accepted, no prompt is shown).
"""

from __future__ import annotations

from forge.sync.project_to_forge.harvester._bundle_writer import HarvestBundle
from forge.sync.project_to_forge.harvester._interactive import (
    HarvestAborted,
    HarvestDecision,
    PromptCallback,
    _run_interactive_review,
)
from forge.sync.project_to_forge.harvester._orchestrator import (
    _emit_cross_lang_suggestions,
    harvest_project,
)

__all__ = [
    "HarvestAborted",
    "HarvestBundle",
    "HarvestDecision",
    "PromptCallback",
    "_emit_cross_lang_suggestions",
    "_run_interactive_review",
    "harvest_project",
]
