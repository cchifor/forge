"""Reverse direction: project → forge (Phase 2 verify_project; Phase 4 harvest).

The reverse flow inspects a generated project against the manifest to
detect drift (today, via ``verify_project``) and — in Phase 4 — extracts
user edits back into candidate fragment patches.
"""

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
    "VerifyReport",
    "VerifyWorst",
    "verify_project",
]
