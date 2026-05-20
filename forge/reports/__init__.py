"""Agent-grade reports for the forge CLI.

Initiative #5 — autonomous agents (Claude Code, Codex, CI runners)
drive forge headlessly and need a richer success envelope than the
pre-existing ``{project_root, backends, frontend_dir, framework,
features}`` shape that :mod:`forge.cli.main` emitted under ``--json``.
This module ships three report dataclasses:

* :class:`GenerationReport` — captured by :func:`forge.generator.generate`
  and surfaced under ``--json`` so the caller can reconstruct *what*
  forge did (effective config, option origins, fragment graph,
  per-file inventory, hidden mutations the CLI applied, warnings,
  skipped toolchains, and the suggested next actions).
* :class:`UpdateReport` — the same shape plus per-file dispositions
  (``unchanged`` / ``modified`` / ``merged`` / ``conflict`` /
  ``sidecar-emitted``) for ``forge --update``.
* :class:`SyncPlanReport` — every candidate of the sync planner gets
  a stable identifier plus an explicit disposition so an agent can
  inspect a proposed sync before applying it. Scaffolded; the planner
  wiring lands in a later commit.

Every report carries a ``_report_version`` integer so future schema
revisions can land additively without breaking consumers that pin a
particular shape. The ``to_dict()`` method drops ``None`` /empty
collections so the rendered JSON stays compact.

The dataclasses live in private leaf modules — ``_generation``,
``_update``, ``_sync_plan`` — re-exported here so the canonical import
path is ``from forge.reports import GenerationReport``.
"""

from __future__ import annotations

from forge.reports._generation import (
    REPORT_VERSION,
    FileInventoryEntry,
    GenerationReport,
    HiddenMutation,
    NextAction,
    SkippedToolchain,
)
from forge.reports._sync_plan import (
    SyncPlanCandidate,
    SyncPlanDisposition,
    SyncPlanReport,
)
from forge.reports._update import (
    FileDisposition,
    UpdateFileEntry,
    UpdateReport,
)

__all__ = [
    "REPORT_VERSION",
    "FileDisposition",
    "FileInventoryEntry",
    "GenerationReport",
    "HiddenMutation",
    "NextAction",
    "SkippedToolchain",
    "SyncPlanCandidate",
    "SyncPlanDisposition",
    "SyncPlanReport",
    "UpdateFileEntry",
    "UpdateReport",
]
