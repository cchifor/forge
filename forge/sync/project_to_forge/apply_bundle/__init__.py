"""Apply harvest-bundle candidates back to the forge fragment tree (Phase 5/6).

Public surface re-exports — see :mod:`._dispatch` for the dispatcher
docstring and :mod:`._files_literal`, :mod:`._files_structural`,
:mod:`._blocks`, :mod:`._deps`, :mod:`._env` for the per-kind handler
modules.
"""

from __future__ import annotations

from forge.sync.project_to_forge.apply_bundle._dispatch import (
    ApplyBundleEntry,
    ApplyBundleReport,
    apply_bundle_to_fragments,
)
from forge.sync.project_to_forge.apply_bundle._files_literal import (
    _is_structural_files_candidate,
)

__all__ = [
    "ApplyBundleEntry",
    "ApplyBundleReport",
    "_is_structural_files_candidate",
    "apply_bundle_to_fragments",
]
