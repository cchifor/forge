"""Reverse direction: project → forge (Phase 2 verify_project; Phase 4 harvest).

The reverse flow inspects a generated project against the manifest to
detect drift (via ``verify_project``) and extract user edits back into
candidate fragment patches (via ``harvest_project``).

* Phase 2: :func:`verify_project` — read-only drift detection.
* Phase 4: :func:`harvest_project` — extract user edits as candidate
  fragment patches. The harvester walks the manifest, runs the
  :class:`forge.extractors.ExtractorPipeline`, and bundles the result
  into a :class:`HarvestBundle` the maintainer can review.
"""

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
    "BlockVerifyEntry",
    "FileVerifyEntry",
    "HarvestBundle",
    "VerifyReport",
    "VerifyWorst",
    "harvest_project",
    "verify_project",
]
