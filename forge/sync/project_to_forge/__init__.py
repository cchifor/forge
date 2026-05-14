"""Reverse direction: project → forge (Phase 2 verify_project; Phase 4 harvest).

The reverse flow inspects a generated project against the manifest to
detect drift (via ``verify_project``) and extract user edits back into
candidate fragment patches (via ``harvest_project``).

* Phase 2: :func:`verify_project` — read-only drift detection.
* Phase 4: :func:`harvest_project` — extract user edits as candidate
  fragment patches. The harvester walks the manifest, runs the
  :class:`forge.extractors.ExtractorPipeline`, and bundles the result
  into a :class:`HarvestBundle` the maintainer can review.
* Phase 5: :func:`apply_bundle_to_fragments` — write a harvest bundle's
  candidates back into the forge fragment tree. Files-only in v1; block
  / deps / env are deferred to Phase 6.
* Phase 6 close: :func:`accept_harvested` — re-stamp the project's
  ``forge.toml`` baselines after a harvest bundle landed upstream, so
  the user's edits become the new manifest baseline rather than drift.
"""

from forge.sync.project_to_forge.accept import (
    AcceptHarvestedEntry,
    AcceptHarvestedReport,
    accept_harvested,
)
from forge.sync.project_to_forge.apply_bundle import (
    ApplyBundleEntry,
    ApplyBundleReport,
    apply_bundle_to_fragments,
)
from forge.sync.project_to_forge.harvester import (
    HarvestBundle,
    harvest_project,
)
from forge.sync.project_to_forge.verify import (
    BlockVerifyEntry,
    FileVerifyEntry,
    VerifyReport,
    VerifyWorst,
    verify_project,
)

__all__ = [
    "AcceptHarvestedEntry",
    "AcceptHarvestedReport",
    "ApplyBundleEntry",
    "ApplyBundleReport",
    "BlockVerifyEntry",
    "FileVerifyEntry",
    "HarvestBundle",
    "VerifyReport",
    "VerifyWorst",
    "accept_harvested",
    "apply_bundle_to_fragments",
    "harvest_project",
    "verify_project",
]
