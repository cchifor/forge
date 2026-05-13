"""ExtractionPlan — what a fragment proposes to extract.

Symmetric to :class:`forge.appliers.plan.FragmentPlan`. The Phase 4
harvester builds one :class:`ExtractionPlan` per resolved fragment by
inverting the applier plan: instead of "this fragment will mutate
target X in way Y", the extraction plan says "search target X for
evidence of user edits relative to baseline Y".

The plan is intentionally a flat record of search targets rather than a
mirror of :class:`~forge.appliers.plan.FragmentPlan`. We don't need to
re-resolve ``inject.yaml`` against the fragment's filesystem at harvest
time — the harvester already has the rendered injections from the
forward plan it inverted, and re-rendering would re-introduce Jinja
state that may have drifted since the last apply.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ExtractionPlan:
    """One fragment's extraction targets.

    Mirror of :class:`forge.appliers.plan.FragmentPlan`.

    Attributes:
        fragment_name: Fragment identity used in :class:`CandidatePatch`
            records and in any diagnostic the extractor emits. Matches
            the ``feature_key`` carried by the forward plan.
        files: Tuple of ``(fragment_relpath, dst_relpath)`` pairs to
            compare. ``fragment_relpath`` is rooted at the fragment's
            ``files/`` directory; ``dst_relpath`` is rooted at the
            backend / project directory the forward applier would have
            written to. Empty for inject-only fragments.
        injections: Sequence of ``_Injection``-shaped records — the
            same rendered injection bodies the forward plan used. Phase
            4 compares each against the body found between the
            BEGIN/END sentinels in the generated project.
        dependencies: Pass-through of the forward plan's ``dependencies``
            tuple. Phase 4 compares each declared dep against the
            current manifest entry (version drift, removed deps, added
            user deps).
        env_vars: Pass-through of the forward plan's ``env_vars`` tuple.
            Phase 4 compares each ``(key, value)`` against the current
            ``.env.example`` value.
    """

    fragment_name: str
    files: tuple[tuple[str, str], ...]
    injections: tuple[Any, ...]
    dependencies: tuple[str, ...]
    env_vars: tuple[tuple[str, str], ...]
