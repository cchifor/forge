"""SyncPlanReport dataclass — scaffolded.

The planner that backs ``forge --plan-update`` (and the harvest /
plan-uninstall flows) currently emits a heterogeneous mix of dicts,
counts, and pretty-printed lines. Initiative #5 introduces a stable
report shape: every candidate gets a deterministic identifier plus
an explicit disposition so an agent can inspect the proposed sync
before applying it.

The dataclass is fully wired (serialisation, ``add_candidate``
helper, schema version) but no production caller emits one yet —
the planner wiring lands in a follow-up. The report exists today
so the test suite can lock in the schema and downstream consumers
can start coding against it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from forge.reports._generation import REPORT_VERSION

# Each candidate the planner considers gets one of these labels:
#
# * ``safe-apply`` — the planner is confident; an agent can apply
#   without asking.
# * ``needs-review`` — the planner can't fully justify the change
#   (e.g. fragment template drifted); a human / agent should look
#   before applying.
# * ``skipped-vacuous`` — the candidate would be a no-op (e.g.
#   the on-disk content already matches the proposed new content).
# * ``conflict`` — the candidate clashes with another candidate
#   (e.g. two fragments propose contradictory writes to the same
#   path).
SyncPlanDisposition = Literal[
    "safe-apply",
    "needs-review",
    "skipped-vacuous",
    "conflict",
]


@dataclass(frozen=True)
class SyncPlanCandidate:
    """One candidate the planner considered.

    ``candidate_id`` is a stable identifier that survives re-running
    the planner — typically ``"{fragment_name}::{path}"`` for a file
    candidate or ``"{fragment_name}::{block_key}"`` for a merge-block
    candidate. ``kind`` discriminates file vs block vs fragment-scope
    candidates. ``rationale`` is a free-form human-readable string.
    """

    candidate_id: str
    kind: str  # "file" / "block" / "fragment"
    disposition: SyncPlanDisposition
    rationale: str = ""
    path: str | None = None
    fragment_name: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "candidate_id": self.candidate_id,
            "kind": self.kind,
            "disposition": self.disposition,
        }
        if self.rationale:
            out["rationale"] = self.rationale
        if self.path:
            out["path"] = self.path
        if self.fragment_name:
            out["fragment_name"] = self.fragment_name
        if self.metadata:
            out["metadata"] = dict(self.metadata)
        return out


@dataclass
class SyncPlanReport:
    """Agent-grade summary of a sync planning pass.

    ``candidates`` lists every candidate the planner considered with
    its disposition. Counts are denormalised into ``totals`` for
    quick scanning. ``warnings`` collects planner-level diagnostics
    (e.g. "the manifest references a fragment that's no longer
    registered").
    """

    project_root: str = ""
    candidates: list[SyncPlanCandidate] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    _report_version: int = REPORT_VERSION

    def add_candidate(self, candidate: SyncPlanCandidate) -> None:
        self.candidates.append(candidate)

    def add_warning(self, msg: str) -> None:
        if msg not in self.warnings:
            self.warnings.append(msg)

    def totals(self) -> dict[str, int]:
        """Per-disposition candidate counts. Re-derived on each call so
        the value stays consistent after ``add_candidate``."""
        buckets: dict[str, int] = {
            "safe-apply": 0,
            "needs-review": 0,
            "skipped-vacuous": 0,
            "conflict": 0,
        }
        for c in self.candidates:
            buckets[c.disposition] = buckets.get(c.disposition, 0) + 1
        return buckets

    def to_dict(self) -> dict[str, Any]:
        return {
            "_report_version": self._report_version,
            "project_root": self.project_root,
            "candidates": [c.to_dict() for c in self.candidates],
            "totals": self.totals(),
            "warnings": list(self.warnings),
        }
