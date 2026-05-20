"""ExtractorPipeline — composes per-kind extractors into a bundle.

Symmetric to :class:`forge.appliers.pipeline.FragmentPipeline`, but
the orchestration is purely additive: each extractor returns a list of
:class:`CandidatePatch` values and the pipeline aggregates them. No
ordering constraints between extractors — they don't share filesystem
state the way appliers do, because extractors only *read*.

Phase 4 of the bidirectional-sync plan plugs the actual harvest logic
into each concrete extractor via :func:`forge.merge.reverse_three_way_decide`
and :func:`forge.merge.reverse_file_three_way_decide`. Phase 3 ships
the pipeline with stub extractors so the wiring is in place and
testable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal, Protocol

from forge.codegen.literal_finder import LiteralEdit
from forge.errors import (
    CANDIDATE_PATCH_BAD_KIND,
    CANDIDATE_PATCH_BAD_RISK,
    FragmentError,
)

if TYPE_CHECKING:
    from forge.extractors.plan import ExtractionPlan
    from forge.fragment_context import FragmentContext


# Typed-port (Initiative #1, sub-task 2). Single source of truth for the
# vocabularies that flow out of an extractor and into harvest UI / bundle
# writer / apply-back dispatch / PR emitter. Subset Literals
# (``ExtractorKind``, ``AcceptHarvestedKind``) compose from these so a
# concrete extractor or accept handler can narrow its expected kinds
# without redefining the alphabet.

CandidateKind = Literal[
    "files",
    "block",
    "deps",
    "env",
    "new-file",
    "cross-lang-suggest",
]
"""Every kind a :class:`CandidatePatch` may carry. ``files`` / ``block``
/ ``deps`` / ``env`` originate from the four built-in extractors;
``new-file`` is emitted by the accept-baseline path for user-authored
files that need restamping; ``cross-lang-suggest`` is a synthetic
record the harvester emits for RFC-006 cross-backend parity hints."""

CandidateRisk = Literal["safe-apply", "needs-review", "conflict"]
"""Classification controlling how the operator reviews the candidate.
``safe-apply`` is auto-acceptable; ``needs-review`` queues for human
review; ``conflict`` requires manual resolution."""

ExtractorKind = Literal["files", "block", "deps", "env"]
"""The subset of ``CandidateKind`` values that concrete extractors
declare as :attr:`ExtractorProtocol.kind`. ``new-file`` and
``cross-lang-suggest`` are produced downstream and never declared by
an extractor."""

CANDIDATE_KINDS: tuple[CandidateKind, ...] = (
    "files",
    "block",
    "deps",
    "env",
    "new-file",
    "cross-lang-suggest",
)
CANDIDATE_RISKS: tuple[CandidateRisk, ...] = (
    "safe-apply",
    "needs-review",
    "conflict",
)
EXTRACTOR_KINDS: tuple[ExtractorKind, ...] = ("files", "block", "deps", "env")


@dataclass(frozen=True)
class CandidatePatch:
    """One proposed patch from a generated project back to a fragment.

    Phase 4 populates these; Phase 3 only defines the shape so the
    pipeline contract is stable.

    Attributes:
        fragment: The fragment this patch would amend. Matches
            :attr:`ExtractionPlan.fragment_name`.
        backend: The backend scope the patch belongs to (e.g. ``api``,
            ``project``). Project-scope patches use the synthetic
            ``project`` backend label, matching ``BackendConfig.name``
            for project-scope fragments.
        kind: One of ``"files"`` / ``"block"`` / ``"deps"`` / ``"env"``
            / ``"new-file"`` / ``"cross-lang-suggest"``. Drives the harvest
            bundle's per-section grouping and the apply-side dispatch when
            the patch lands back in a fragment.

            Emitted by extractor:

            * ``"files"`` — :class:`forge.extractors.files.FileExtractor`
              detects a fragment-shipped file that the user has edited
              under the project tree.
            * ``"block"`` —
              :class:`forge.extractors.injection.InjectionExtractor`
              detects a user edit between BEGIN/END sentinels for a
              ``inject.yaml``-managed snippet.
            * ``"deps"`` / ``"env"`` — the matching pair extractors
              detect drift between the fragment's declared deps/env
              and the project's manifest.
            * ``"new-file"`` — reserved for bundles authored against
              the accept-baseline path
              (:mod:`forge.sync.project_to_forge.accept`), which works
              over raw manifest entries that may carry this kind. No
              built-in extractor emits ``new-file`` as a
              :class:`CandidatePatch` today; the accept handler
              constructs :class:`AcceptHarvestedEntry` directly. Kept
              in :data:`CANDIDATE_KINDS` so a bundle whose JSON
              survived a round-trip still deserializes cleanly through
              :class:`CandidatePatch`, and so apply-back dispatch can
              surface a structured "errored" entry when an agent
              forwards one of these to ``apply_bundle_to_fragments``
              instead of the accept path.
            * ``"cross-lang-suggest"`` — synthetic candidate emitted by
              the harvester's cross-language parity pass (RFC-006). For
              each ``"block"`` candidate harvested from a tier-1
              fragment, sibling candidates are emitted naming the
              parallel impls on every OTHER built-in backend so the
              maintainer can mirror the edit. These candidates carry no
              applicable diff and are not committed by ``forge
              --emit-pr``; the PR body's reviewer checklist surfaces
              them instead.
        rel_path: POSIX rel-path identifying the patch target. For
            ``"files"`` this is the fragment-relative path; for
            ``"block"`` it is the inject.yaml target; for ``"deps"`` it
            is the manifest path; for ``"env"`` it is ``".env.example"``.
        target_path: Absolute path on disk to the project-side file the
            patch was harvested from. Recorded so reviewers can trace a
            candidate back to its origin without re-running the
            harvest.
        diff: Unified diff text the harvester would write into the
            fragment. Empty when ``kind == "deps"`` or ``"env"`` and the
            patch is a single line append — see the per-extractor doc.
        baseline_sha: SHA recorded in ``forge.toml`` for this target the
            last time forge ran. ``None`` for pre-1.1 / untracked
            entries, which the harvester promotes to ``"needs-review"``
            because there's no anchor for the three-way comparison.
        current_sha: SHA of the on-disk state right now. Combined with
            ``baseline_sha`` and the upstream fragment SHA, the
            harvester classifies the patch via
            :func:`forge.merge.reverse_three_way_decide`.
        risk: Classification controlling how the operator reviews the
            candidate. One of:

            * ``"safe-apply"`` — fragment didn't move; user is the only
              delta; literals-only. Auto-acceptable.
            * ``"needs-review"`` — Jinja interpolation touched,
              multi-line rewrite, or large delta. Diff goes to the
              review queue.
            * ``"conflict"`` — both moved divergently OR extractor
              cannot anchor. Operator must resolve by hand.
        rationale: Free-form note from the extractor explaining the
            classification. Surfaced in ``forge --harvest`` review UI;
            omitted from non-interactive bundle output.
        current_body: Post-edit body the patch would write back. Populated
            differently per ``kind`` so the apply-back path can rewrite
            the upstream source without re-reading the project tree:

            * ``"block"`` — the on-disk body between the BEGIN/END
              sentinels (exclusive of the sentinel lines themselves).
              Required by :func:`apply_bundle_to_fragments` to rewrite
              the fragment's ``inject.yaml`` ``snippet:`` entry.
            * ``"files"`` — the full post-edit file content as a string
              (text files only). Empty for binary files; the apply-back
              path falls back to reading ``target_path`` directly in
              that case.
            * ``"new-file"`` — the user-authored file content.
            * ``"deps"`` / ``"env"`` — left empty. Those kinds emit
              structural-JSON diffs and reason about the manifest
              shape, not raw content.
        feature_key: For ``kind="block"`` candidates, the feature key
            recorded in the BEGIN/END sentinel (e.g. ``"middleware_cors"``).
            Combined with ``marker`` it pins the exact ``inject.yaml``
            entry the apply-back step rewrites. Empty for non-block
            kinds.
        marker: For ``kind="block"`` candidates, the sentinel marker
            (e.g. ``"FORGE:MIDDLEWARE_REGISTRATION"``). Empty for
            non-block kinds.
        option_promotion: For ``kind="block"`` candidates whose user edit
            is detected as a pure literal-value swap (see
            :mod:`forge.codegen.literal_finder`), the tuple of
            :class:`~forge.codegen.literal_finder.LiteralEdit` records
            describing each changed literal. Drives the side-car
            ``option-promote`` patch the bundle emits next to the main
            candidate file — see
            :func:`forge.sync.project_to_forge.bundle._write_patches`.
            Empty tuple for every other case (structural diffs, deps /
            env / files kinds, Jinja-overlapping edits).
    """

    fragment: str
    backend: str
    kind: CandidateKind
    rel_path: str
    target_path: str
    diff: str
    baseline_sha: str | None
    current_sha: str
    risk: CandidateRisk
    rationale: str = ""
    current_body: str = ""
    feature_key: str = ""
    marker: str = ""
    option_promotion: tuple[LiteralEdit, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        # Construction-time gate for callers that bypass the per-extractor
        # builders — bundle deserialization, plugin extractors, future
        # codepaths that read CandidatePatch records from JSON. The
        # extractor-side construction sites use string literals that ``ty``
        # already validates against ``CandidateKind`` / ``CandidateRisk``.
        if self.kind not in CANDIDATE_KINDS:
            raise FragmentError(
                f"CandidatePatch.kind must be one of {list(CANDIDATE_KINDS)!r}, "
                f"got {self.kind!r}",
                code=CANDIDATE_PATCH_BAD_KIND,
                context={"kind": str(self.kind), "fragment": self.fragment},
            )
        if self.risk not in CANDIDATE_RISKS:
            raise FragmentError(
                f"CandidatePatch.risk must be one of {list(CANDIDATE_RISKS)!r}, "
                f"got {self.risk!r}",
                code=CANDIDATE_PATCH_BAD_RISK,
                context={"risk": str(self.risk), "fragment": self.fragment},
            )


class ExtractorProtocol(Protocol):
    """Contract for each concrete extractor.

    Phase 4 implementations call back into :mod:`forge.merge` (the
    reverse three-way decide functions) and :mod:`forge.provenance`
    (classify) to compute the diff between project state and fragment
    baseline. The protocol is intentionally minimal — extractors must
    not mutate ``ctx`` or the filesystem; they only read.

    Implementers expose:

    * :attr:`kind` — one of :data:`ExtractorKind` (the
      ``"files"`` / ``"block"`` / ``"deps"`` / ``"env"`` subset of
      :data:`CandidateKind`). Drives plugin-side overrides via
      :meth:`forge.api.ForgeAPI.add_extractor` and tags emitted
      :class:`CandidatePatch` records.
    * :meth:`extract` — returns the candidate patches this extractor
      found for ``plan``.
    """

    kind: ExtractorKind

    def extract(
        self,
        ctx: FragmentContext,
        plan: ExtractionPlan,
    ) -> list[CandidatePatch]: ...


@dataclass
class ExtractorPipeline:
    """Compose multiple extractors into a single pass.

    Construct with the four built-in extractors via :meth:`default` or
    pass your own tuple. Order is preserved but not semantically
    significant — each extractor reads independent state. Plugins that
    swap an extractor for a fragment-scoped variant build their own
    tuple via :meth:`forge.api.ForgeAPI.add_extractor`.
    """

    extractors: tuple[ExtractorProtocol, ...] = field(default_factory=tuple)

    @classmethod
    def default(cls) -> ExtractorPipeline:
        """Factory for the four built-in extractors.

        Imports the concrete classes lazily so this module can be
        imported without dragging in the full extractor surface — useful
        for plugin SDK consumers that only need the protocol shapes.
        """
        from forge.extractors.deps import DepsExtractor  # noqa: PLC0415
        from forge.extractors.env import EnvExtractor  # noqa: PLC0415
        from forge.extractors.files import FileExtractor  # noqa: PLC0415
        from forge.extractors.injection import InjectionExtractor  # noqa: PLC0415

        return cls(
            extractors=(
                FileExtractor(),
                InjectionExtractor(),
                DepsExtractor(),
                EnvExtractor(),
            )
        )

    def run(self, ctx: FragmentContext, plan: ExtractionPlan) -> list[CandidatePatch]:
        """Aggregate candidate patches from every registered extractor."""
        out: list[CandidatePatch] = []
        for extractor in self.extractors:
            out.extend(extractor.extract(ctx, plan))
        return out
