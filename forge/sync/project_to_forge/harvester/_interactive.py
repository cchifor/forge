"""Interactive review (Theme 2C — ``--harvest-interactive``).

Split out from the original ``harvester.py`` god module — see
:mod:`forge.sync.project_to_forge.harvester` for the public surface.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal

from forge.extractors.pipeline import CandidatePatch


# Result tokens a ``prompt_callback`` may return per candidate. ``"quit"``
# short-circuits the harvest: the caller receives a :class:`HarvestAborted`
# rather than a partial :class:`HarvestBundle` (and no on-disk bundle is
# written). ``"skip"`` drops the candidate from the bundle but lets the
# loop continue to the next one. ``"accept"`` keeps the candidate.
HarvestDecision = Literal["accept", "skip", "quit"]

# Signature of the per-candidate prompt callback. The harvester passes the
# candidate plus ``(index, total)`` for "N of M"-style progress display.
# Implementations live in :mod:`forge.cli.interactive` (real TUI) and in
# tests (deterministic deque-of-decisions stub). The default of ``None``
# threaded through :func:`harvest_project` means "accept every candidate"
# — preserving the legacy non-interactive contract.
PromptCallback = Callable[[CandidatePatch, int, int], HarvestDecision]


class HarvestAborted(Exception):
    """Raised when the operator selects ``quit`` at the interactive prompt.

    Carries the partial candidate list inspected so far purely for
    diagnostics; callers MUST NOT persist it — the contract is "quit
    aborts cleanly, no partial bundle written". The CLI dispatcher
    catches this and exits cleanly.
    """

    def __init__(self, inspected_count: int) -> None:
        super().__init__(
            f"Harvest aborted by operator after inspecting {inspected_count} candidate(s)."
        )
        self.inspected_count = inspected_count


def _run_interactive_review(
    candidates: list[CandidatePatch],
    prompt_callback: PromptCallback,
) -> list[CandidatePatch]:
    """Drive the per-candidate accept/skip/quit prompt loop.

    Iterates ``candidates`` in their natural emission order, calling
    ``prompt_callback`` once per entry with ``(index, total)`` so the UI
    can render a "Candidate N of M" header. ``"accept"`` keeps the
    candidate; ``"skip"`` drops it; ``"quit"`` raises
    :class:`HarvestAborted` carrying the count of candidates inspected
    so far.

    Unknown return values from a buggy callback are treated as
    ``"skip"`` rather than crashing — the cost of a dropped candidate
    is recoverable (re-run harvest) where a TypeError in the middle of
    a review pass loses operator state. We keep this defensive but
    silent; harness tests assert the legal vocabulary.
    """
    accepted: list[CandidatePatch] = []
    total = len(candidates)
    for idx, cand in enumerate(candidates, start=1):
        decision = prompt_callback(cand, idx, total)
        if decision == "accept":
            accepted.append(cand)
        elif decision == "quit":
            raise HarvestAborted(inspected_count=idx)
        # "skip" (or any unknown token) → drop the candidate silently.
    return accepted
