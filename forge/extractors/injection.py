"""InjectionExtractor — reverse counterpart of :mod:`forge.appliers.injection`.

Where :class:`forge.appliers.injection.FragmentInjectionApplier` writes
fragment-rendered snippets between BEGIN/END sentinels in target files,
this extractor reads those same regions and harvests user edits.

Phase 4 implements block-level harvest using
:func:`forge.sync.merge.reverse_three_way_decide`. For each injection
record in :attr:`~forge.extractors.plan.ExtractionPlan.injections`, the
extractor:

1. Locates the BEGIN/END sentinel block in the on-disk target file
   under ``ctx.backend_dir / inj.target``.
2. Reads the manifest's baseline SHA for that block from
   ``ctx.merge_block_baselines`` (POSIX rel-path keyed by manifest key).
3. Compares the current body against the upstream fragment-rendered
   snippet via :func:`forge.sync.merge.reverse_three_way_decide`.
4. Emits a :class:`~forge.extractors.pipeline.CandidatePatch` of kind
   ``"block"`` per divergent block.

The trickier classification cases live here:

* Multi-line block edits — even pure-literal — are flagged
  ``"needs-review"`` when the upstream snippet contains a Jinja
  interpolation site (``{{ }}`` / ``{% %}``); the harvester can't safely
  back-port literal edits into a template that re-renders at apply time.
* Missing sentinel pair — when forward provenance says a block was
  applied but the project no longer contains the markers — emits
  ``"conflict"``: the user (or another tool) stripped the markers
  and the extractor cannot anchor.
* ``no-baseline`` (v1 manifest entries without recorded sha) and
  ``skipped-*`` outcomes don't emit a candidate.
"""

from __future__ import annotations

import difflib
import re
from typing import TYPE_CHECKING, Any

from forge.errors import FragmentError
from forge.extractors.pipeline import CandidatePatch
from forge.injectors.sentinels import _read_block_body
from forge.sync.merge import reverse_three_way_decide, sha256_of_text

if TYPE_CHECKING:
    from pathlib import Path

    from forge.extractors.plan import ExtractionPlan
    from forge.fragment_context import FragmentContext

# Detects Jinja interpolation / statement sites in an upstream snippet.
# A user edit overlapping such a site is unsafe to back-port literally
# because the upstream template re-renders at apply time — the literal
# string the user saw on disk is not what the fragment ships.
_JINJA_PATTERN = re.compile(r"\{\{|\{%")


class InjectionExtractor:
    """Harvest user edits to fragment-injected blocks."""

    kind = "block"

    def extract(
        self,
        ctx: FragmentContext,
        plan: ExtractionPlan,
    ) -> list[CandidatePatch]:
        """Return harvested candidates for ``plan.injections``.

        For each injection record, reads the on-disk block body between
        the BEGIN/END sentinels, looks up the manifest baseline + upstream
        snippet (from the fragment's inject.yaml), and classifies the
        divergence via :func:`forge.sync.merge.reverse_three_way_decide`.

        Returns a list of :class:`CandidatePatch` records — one per
        block that produced a ``safe-apply`` or ``conflict`` outcome.
        Skipped outcomes (``skipped-*``, ``no-baseline``) yield no entry.
        """
        if not plan.injections:
            return []

        baselines: dict[str, dict[str, Any]] = _read_merge_baselines(ctx)

        candidates: list[CandidatePatch] = []
        for inj in plan.injections:
            patch = self._extract_one(ctx=ctx, plan=plan, inj=inj, baselines=baselines)
            if patch is not None:
                candidates.append(patch)
        return candidates

    def _extract_one(
        self,
        *,
        ctx: FragmentContext,
        plan: ExtractionPlan,
        inj: Any,  # _Injection — typed via duck-attribute access
        baselines: dict[str, dict[str, Any]],
    ) -> CandidatePatch | None:
        # Resolve project-side path for the manifest key lookup. The
        # injection's ``target`` is rooted at ``backend_dir`` (a
        # fragment-private path); the manifest stores keys rooted at
        # ``project_root``. Bridge both.
        target_path: Path = ctx.backend_dir / inj.target
        rel_to_project = _project_rel_path(target_path=target_path, project_root=ctx.project_root)

        marker = inj.marker
        feature_key = inj.feature_key
        manifest_key = _manifest_key(rel_to_project, feature_key, marker)
        entry = baselines.get(manifest_key)
        baseline_sha = str(entry.get("sha256", "")) if entry else None
        fragment_name = (entry.get("fragment_name") if entry else None) or plan.fragment_name
        fragment_name = str(fragment_name) if fragment_name else plan.fragment_name

        # Upstream rendered body the fragment would emit right now. We
        # already have a rendered snippet on ``inj.snippet`` from the
        # ExtractionPlan, but the harvest-time render is what we compare
        # against — re-render to capture any drift in the upstream
        # template that the plan was built from. Fall back to the raw
        # snippet (with a needs-review note) when rendering would fail.
        upstream_body, render_failed = _resolve_upstream_body(inj, options=dict(ctx.options))

        # Sentinel for "orchestrator couldn't reach the upstream
        # snippet" (fragment disabled, inject.yaml missing, etc.) OR
        # render failed against the project's option values (Jinja
        # template needs context we don't have at harvest time). In
        # both cases we cannot safely run a three-way decide — fall
        # back to the baseline-only path and emit ``needs-review``.
        upstream_unavailable = (
            not str(getattr(inj, "snippet", "")) and not upstream_body
        ) or render_failed

        # Read the on-disk block body. Missing sentinels → ``conflict``.
        current_body = _read_block_body(target_path, feature_key, marker)
        if current_body is None:
            # The forward applier recorded a block here but the user (or
            # another tool) has removed the sentinels. We can't anchor
            # the comparison, so surface as a conflict with no diff —
            # the reviewer must inspect the file by hand.
            return CandidatePatch(
                fragment=fragment_name,
                backend=ctx.backend_config.name,
                kind="block",
                rel_path=inj.target,
                target_path=str(target_path),
                diff="",
                baseline_sha=baseline_sha,
                current_sha="",
                risk="conflict",
                rationale=(
                    "block sentinels missing or corrupt; cannot anchor harvest "
                    "against the recorded baseline"
                ),
            )

        current_sha = sha256_of_text(current_body)

        # When the orchestrator couldn't reach the upstream snippet
        # (fragment unregistered / inject.yaml missing), fall back to
        # a baseline-only comparison. We know whether the user moved
        # off baseline, but not whether upstream did — so a divergent
        # current emits ``needs-review`` with a clear rationale rather
        # than a misleading ``conflict``.
        if upstream_unavailable:
            if baseline_sha is None:
                # No baseline either — pre-1.2 manifest entry with no
                # SHA. Nothing to harvest against.
                return None
            if current_sha == baseline_sha:
                # Block unchanged on disk; no harvest needed.
                return None
            # Synthesize an empty-upstream diff so the reviewer at
            # least sees the current body.
            diff = "".join(
                difflib.unified_diff(
                    [],
                    current_body.splitlines(keepends=True),
                    fromfile=f"a/{inj.target}#{feature_key}:{_naked_marker(marker)}",
                    tofile=f"b/{inj.target}#{feature_key}:{_naked_marker(marker)}",
                )
            )
            rationale = (
                "user edited block; upstream snippet could not be "
                "rendered with the project's options — reviewer must "
                "check the fragment template for Jinja drift"
                if render_failed
                else "user edited block; upstream snippet not reachable "
                "(fragment disabled or inject.yaml missing) — "
                "reviewer must compare against the current fragment"
            )
            return CandidatePatch(
                fragment=fragment_name,
                backend=ctx.backend_config.name,
                kind="block",
                rel_path=inj.target,
                target_path=str(target_path),
                diff=diff,
                baseline_sha=baseline_sha,
                current_sha=current_sha,
                risk="needs-review",
                rationale=rationale,
            )

        decision = reverse_three_way_decide(
            baseline_sha=baseline_sha,
            current_body=current_body,
            upstream_body=upstream_body,
        )

        # ``no-baseline`` and ``skipped-*`` outcomes don't promote a
        # harvest candidate. ``no-baseline`` means the manifest is v1
        # without a recorded SHA; ``skipped-idempotent`` / ``-no-change``
        # mean there is nothing for the harvester to do.
        if decision in ("no-baseline", "skipped-idempotent", "skipped-no-change"):
            return None

        # Render the upstream→current unified diff. Even on conflict we
        # ship the diff so the reviewer can see the user's changes.
        diff = "".join(
            difflib.unified_diff(
                upstream_body.splitlines(keepends=True),
                current_body.splitlines(keepends=True),
                fromfile=f"a/{inj.target}#{feature_key}:{_naked_marker(marker)}",
                tofile=f"b/{inj.target}#{feature_key}:{_naked_marker(marker)}",
            )
        )

        if decision == "conflict":
            return CandidatePatch(
                fragment=fragment_name,
                backend=ctx.backend_config.name,
                kind="block",
                rel_path=inj.target,
                target_path=str(target_path),
                diff=diff,
                baseline_sha=baseline_sha,
                current_sha=current_sha,
                risk="conflict",
                rationale="user and upstream both diverged from the recorded baseline",
            )

        # decision == "safe-apply" — user edited, upstream unchanged.
        # Downgrade to needs-review when the (successfully-rendered)
        # upstream snippet still contains Jinja interpolation: a
        # literal edit harvested into a template would round-trip
        # incorrectly on re-render. The ``render_failed`` case was
        # already handled via the ``upstream_unavailable`` short-circuit
        # above; ``_JINJA_PATTERN.search`` here catches the rarer case
        # of a fragment whose rendered output legitimately includes
        # ``{{ }}`` (e.g. a code generator emitting Jinja).
        if _JINJA_PATTERN.search(upstream_body):
            return CandidatePatch(
                fragment=fragment_name,
                backend=ctx.backend_config.name,
                kind="block",
                rel_path=inj.target,
                target_path=str(target_path),
                diff=diff,
                baseline_sha=baseline_sha,
                current_sha=current_sha,
                risk="needs-review",
                rationale=(
                    "user edit overlaps an upstream Jinja interpolation site; "
                    "literal back-port would corrupt the template"
                ),
            )

        return CandidatePatch(
            fragment=fragment_name,
            backend=ctx.backend_config.name,
            kind="block",
            rel_path=inj.target,
            target_path=str(target_path),
            diff=diff,
            baseline_sha=baseline_sha,
            current_sha=current_sha,
            risk="safe-apply",
            rationale="user edited block; upstream fragment template unchanged",
        )


def _read_merge_baselines(ctx: FragmentContext) -> dict[str, dict[str, Any]]:
    """Pull the manifest's ``[forge.merge_blocks]`` table for this project.

    The harvester orchestrator typically populates a side-channel on
    ``ctx`` (see :class:`forge.fragment_context.FragmentContext`); for
    backward-compat we fall back to reading the manifest directly from
    ``ctx.project_root`` so this extractor stays self-sufficient when
    called from a test fixture that bypasses the orchestrator.
    """
    explicit = getattr(ctx, "merge_block_baselines", None)
    if isinstance(explicit, dict):
        return {str(k): dict(v) for k, v in explicit.items()}

    # Lazy import — keeps the module load cheap for unit tests that
    # construct a FragmentContext directly without a manifest.
    from forge.sync.manifest import read_forge_toml  # noqa: PLC0415

    manifest = ctx.project_root / "forge.toml"
    if not manifest.is_file():
        return {}
    try:
        data = read_forge_toml(manifest)
    except Exception:  # noqa: BLE001 — caller treats no-baseline as no candidate.
        return {}
    return {str(k): dict(v) for k, v in data.merge_blocks.items()}


def _resolve_upstream_body(inj: Any, *, options: dict[str, Any]) -> tuple[str, bool]:
    """Return the upstream rendered body for an injection record.

    ``inj.snippet`` is the rendered body the forward plan computed —
    the extractor plan threads it through verbatim. We attempt a
    re-render under the project's current options to catch the case
    where the fragment's upstream snippet (raw, in ``inject.yaml``)
    has drifted between plan-build time and harvest time. When
    rendering fails — undefined variable, malformed template — we
    return the as-stored snippet and flag ``render_failed=True`` so the
    classifier can downgrade to ``needs-review``.

    Returns ``(rendered_body, render_failed)``.
    """
    raw_snippet = str(getattr(inj, "snippet", ""))
    # The plan-time snippet is already rendered. Check whether the
    # snippet text itself carries Jinja markers — if it does, that
    # means the rendered output legitimately contains ``{{ }}`` (rare
    # but legal for code emitting templates), and we should leave it
    # as-is.
    if not _JINJA_PATTERN.search(raw_snippet):
        return raw_snippet, False

    # Re-render with the current options. The forward applier uses
    # :func:`forge.feature_injector._render_snippet`; we delegate so
    # the rendering semantics stay identical.
    try:
        from forge.feature_injector import _render_snippet  # noqa: PLC0415

        return _render_snippet(raw_snippet, options), False
    except FragmentError:
        return raw_snippet, True
    except Exception:  # noqa: BLE001 — unknown render failure → needs-review.
        return raw_snippet, True


def _manifest_key(rel_posix_path: str, feature_key: str, marker: str) -> str:
    """Build a manifest key matching :meth:`MergeBlockCollector.key_for`.

    Inlined here to avoid pulling the collector module just for one
    static method — the format is part of the public manifest contract.
    """
    naked = _naked_marker(marker)
    return f"{rel_posix_path}::{feature_key}:{naked}"


def _naked_marker(marker: str) -> str:
    """Strip the ``FORGE:`` prefix from a marker name."""
    return marker.removeprefix("FORGE:") if marker.startswith("FORGE:") else marker


def _project_rel_path(*, target_path: Path, project_root: Path) -> str:
    """POSIX rel-path of ``target_path`` against ``project_root``.

    Falls back to ``target_path.as_posix()`` when the target lives
    outside the project tree (synthetic test fixture).
    """
    try:
        return target_path.relative_to(project_root).as_posix()
    except ValueError:
        return target_path.as_posix()
