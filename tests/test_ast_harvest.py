"""End-to-end tests for item-6 AST-level harvest.

Exercises the integration between
:class:`forge.extractors.injection.InjectionExtractor`,
:mod:`forge.codegen.literal_finder`, and
:func:`forge.sync.project_to_forge.bundle.write_bundle`:

1. A user's literal-value edit to a fragment-emitted block surfaces as a
   ``safe-apply`` candidate with a populated
   :attr:`CandidatePatch.option_promotion` field.
2. The bundle writer emits a side-car ``NNNN-option-promote-<safe_key>.patch``
   file next to the main patch.
3. Telemetry emits ``harvest.option_promotion_suggested`` (once per
   detected :class:`LiteralEdit`).
4. Literals overlapping a Jinja interpolation site stay ``needs-review`` —
   no option-promotion suggestion.
5. Structural changes (added lines) skip the literal-promotion path.
6. Rust / TypeScript-off candidates skip the literal-promotion path.

These are integration tests built around the existing ``test_harvest.py``
scaffolding pattern: a tmp_path with a forge.toml + sentinel-wrapped block.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from forge import telemetry
from forge.codegen.literal_finder import LiteralEdit
from forge.config import BackendConfig, BackendLanguage
from forge.extractors import ExtractionPlan, InjectionExtractor
from forge.fragment_context import FragmentContext
from forge.fragments import MARKER_PREFIX
from forge.sync.merge import MergeBlockCollector, sha256_of_text
from forge.sync.project_to_forge.bundle import write_bundle
from forge.sync.project_to_forge.harvester import HarvestBundle

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _block_text(feature_key: str, marker_bare: str, body: str) -> str:
    """Render a sentinel-wrapped block matching the injector's output."""
    return (
        f"# {MARKER_PREFIX}BEGIN {feature_key}:{marker_bare}\n"
        f"{body}"
        f"# {MARKER_PREFIX}END {feature_key}:{marker_bare}\n"
    )


def _scaffold_block_project(
    tmp_path: Path,
    *,
    baseline_body: str,
    edited_body: str | None = None,
    backend_name: str = "api",
    feature_key: str = "middleware_rate_limit",
    marker_bare: str = "RATE_LIMIT_CONFIG",
    language: BackendLanguage = BackendLanguage.PYTHON,
) -> dict[str, Any]:
    """Build a project tree with one tracked block.

    The on-disk file initially carries ``baseline_body`` between
    BEGIN/END sentinels. If ``edited_body`` is provided, the file is
    rewritten to that body — simulating a user edit between the
    initial generate + the harvest.
    """
    backend_dir = tmp_path / "services" / backend_name
    src = backend_dir / "src" / "app"
    src.mkdir(parents=True)
    target = src / "main.py"
    initial_block = _block_text(feature_key, marker_bare, baseline_body)
    target.write_text(f"# header\n{initial_block}# footer\n")

    rel_path_in_project = f"services/{backend_name}/src/app/main.py"
    block_key = MergeBlockCollector.key_for(rel_path_in_project, feature_key, marker_bare)
    baseline_sha = sha256_of_text(baseline_body)

    if edited_body is not None:
        edited_block = _block_text(feature_key, marker_bare, edited_body)
        target.write_text(f"# header\n{edited_block}# footer\n")

    return {
        "backend_dir": backend_dir,
        "target": target,
        "block_key": block_key,
        "baseline_sha": baseline_sha,
        "baseline_body": baseline_body,
        "edited_body": edited_body,
        "feature_key": feature_key,
        "marker_bare": marker_bare,
        "language": language,
    }


def _mk_ctx(
    tmp_path: Path,
    *,
    block_key: str,
    baseline_sha: str,
    feature_key: str,
    backend_name: str = "api",
    language: BackendLanguage = BackendLanguage.PYTHON,
) -> FragmentContext:
    """Build a FragmentContext with the merge-block baseline pre-loaded."""
    backend_dir = tmp_path / "services" / backend_name
    ctx = FragmentContext(
        backend_config=BackendConfig(
            name=backend_name,
            project_name="demo",
            language=language,
        ),
        backend_dir=backend_dir,
        project_root=tmp_path,
        options={},
        provenance=None,
    )
    object.__setattr__(
        ctx,
        "merge_block_baselines",
        {
            block_key: {
                "sha256": baseline_sha,
                "fragment_name": feature_key,
            }
        },
    )
    return ctx


class _Inj:
    """Duck-typed :class:`_Injection` record for tests."""

    def __init__(
        self,
        *,
        feature_key: str,
        target: str,
        marker: str,
        snippet: str,
    ) -> None:
        self.feature_key = feature_key
        self.target = target
        self.marker = marker
        self.snippet = snippet


def _mk_plan(meta: dict[str, Any]) -> ExtractionPlan:
    return ExtractionPlan(
        fragment_name=meta["feature_key"],
        files=(),
        injections=(
            _Inj(
                feature_key=meta["feature_key"],
                target="src/app/main.py",
                marker=f"FORGE:{meta['marker_bare']}",
                snippet=meta["baseline_body"],
            ),
        ),
        dependencies=(),
        env_vars=(),
    )


# ---------------------------------------------------------------------------
# Item-6: AST-level literal harvest at the InjectionExtractor layer
# ---------------------------------------------------------------------------


class TestLiteralEditPromotion:
    """Pure literal swaps surface as safe-apply + option_promotion."""

    def test_int_literal_edit_emits_safe_apply_with_promotion(self, tmp_path: Path) -> None:
        # Python block with a single int literal — user changes 120 → 60.
        baseline = "RATE_LIMIT = 120\n"
        edited = "RATE_LIMIT = 60\n"
        meta = _scaffold_block_project(tmp_path, baseline_body=baseline, edited_body=edited)
        ctx = _mk_ctx(
            tmp_path,
            block_key=meta["block_key"],
            baseline_sha=meta["baseline_sha"],
            feature_key=meta["feature_key"],
        )
        plan = _mk_plan(meta)

        patches = InjectionExtractor().extract(ctx, plan)
        assert len(patches) == 1
        patch = patches[0]
        assert patch.risk == "safe-apply"
        # option_promotion is populated and reports the int swap.
        assert len(patch.option_promotion) == 1
        edit = patch.option_promotion[0]
        assert isinstance(edit, LiteralEdit)
        assert edit.kind == "int"
        assert edit.old_value == "120"
        assert edit.new_value == "60"

    def test_two_literals_in_one_block_emit_two_promotion_records(self, tmp_path: Path) -> None:
        # Two literal swaps in one block — the option_promotion field
        # carries both records in source order.
        baseline = 'RATE_LIMIT = 120\nNAME = "alpha"\n'
        edited = 'RATE_LIMIT = 60\nNAME = "beta"\n'
        meta = _scaffold_block_project(tmp_path, baseline_body=baseline, edited_body=edited)
        ctx = _mk_ctx(
            tmp_path,
            block_key=meta["block_key"],
            baseline_sha=meta["baseline_sha"],
            feature_key=meta["feature_key"],
        )
        plan = _mk_plan(meta)

        patches = InjectionExtractor().extract(ctx, plan)
        assert len(patches) == 1
        patch = patches[0]
        assert patch.risk == "safe-apply"
        assert len(patch.option_promotion) == 2
        kinds = [e.kind for e in patch.option_promotion]
        assert kinds == ["int", "str"]


class TestStructuralChangeNoPromotion:
    """Non-literal edits leave option_promotion empty."""

    def test_added_line_has_no_promotion(self, tmp_path: Path) -> None:
        # Adding a statement is structural — falls back to plain safe-apply.
        baseline = "x = 1\n"
        edited = "x = 1\ny = 2\n"
        meta = _scaffold_block_project(tmp_path, baseline_body=baseline, edited_body=edited)
        ctx = _mk_ctx(
            tmp_path,
            block_key=meta["block_key"],
            baseline_sha=meta["baseline_sha"],
            feature_key=meta["feature_key"],
        )
        plan = _mk_plan(meta)

        patches = InjectionExtractor().extract(ctx, plan)
        assert len(patches) == 1
        patch = patches[0]
        assert patch.risk == "safe-apply"
        # Structural change → empty option_promotion.
        assert patch.option_promotion == ()


class TestJinjaOverlapNoPromotion:
    """Literal edits on lines carrying Jinja stay needs-review."""

    def test_jinja_overlap_keeps_needs_review(self, tmp_path: Path) -> None:
        # Upstream is a Jinja template; rendered baseline is what's
        # on disk. The user edits the literal, but the upstream line
        # for that literal also carries ``{{ }}`` — promotion is
        # unsafe; we stay needs-review.
        rendered_baseline = "rate_limit = 100\n"
        edited = "rate_limit = 200\n"
        meta = _scaffold_block_project(
            tmp_path, baseline_body=rendered_baseline, edited_body=edited
        )
        ctx = _mk_ctx(
            tmp_path,
            block_key=meta["block_key"],
            baseline_sha=meta["baseline_sha"],
            feature_key=meta["feature_key"],
        )
        # Upstream snippet is the raw Jinja template.
        plan = ExtractionPlan(
            fragment_name=meta["feature_key"],
            files=(),
            injections=(
                _Inj(
                    feature_key=meta["feature_key"],
                    target="src/app/main.py",
                    marker=f"FORGE:{meta['marker_bare']}",
                    snippet="rate_limit = {{ rate_limit }}\n",
                ),
            ),
            dependencies=(),
            env_vars=(),
        )

        patches = InjectionExtractor().extract(ctx, plan)
        assert len(patches) == 1
        patch = patches[0]
        # The extractor re-renders the snippet with the project's
        # options; with no ``rate_limit`` in scope, render_failed
        # triggers the upstream_unavailable branch → needs-review.
        # Either way the option-promotion field stays empty.
        assert patch.risk == "needs-review"
        assert patch.option_promotion == ()


class TestRustBackendPromotesLiterals:
    """v2 Theme 3B — Rust backends now emit literal-promotion suggestions.

    Was ``TestRustBackendNoPromotion``: the v1 finder returned ``()``
    for any Rust input, so the candidate fell through to a plain
    ``safe-apply`` with an empty ``option_promotion``. Wiring
    tree-sitter-rust into ``literal_finder.py`` flips that behaviour —
    Axum (and any other tree-sitter-rust target) now participates in
    the option-promotion path on a pure literal swap.
    """

    def test_rust_backend_emits_promotion_on_literal_swap(self, tmp_path: Path) -> None:
        # A complete Rust function so tree-sitter parses cleanly. The
        # block scaffolding wraps the body in BEGIN/END sentinel
        # comments, which are stripped before the finder sees them.
        baseline = "fn rate_limit() -> u32 { 120 }\n"
        edited = "fn rate_limit() -> u32 { 60 }\n"
        meta = _scaffold_block_project(
            tmp_path,
            baseline_body=baseline,
            edited_body=edited,
            language=BackendLanguage.RUST,
        )
        ctx = _mk_ctx(
            tmp_path,
            block_key=meta["block_key"],
            baseline_sha=meta["baseline_sha"],
            feature_key=meta["feature_key"],
            language=BackendLanguage.RUST,
        )
        plan = _mk_plan(meta)

        patches = InjectionExtractor().extract(ctx, plan)
        assert len(patches) == 1
        assert patches[0].risk == "safe-apply"
        # The lit-edits surface as option_promotion entries — one per
        # detected literal swap. The exact field shape is the same as
        # the Python path covered above.
        assert len(patches[0].option_promotion) == 1
        edit = patches[0].option_promotion[0]
        assert isinstance(edit, LiteralEdit)
        assert edit.kind == "int"
        assert edit.old_value == "120"
        assert edit.new_value == "60"


class TestTypescriptOffNoPromotion:
    """Node backends without FORGE_TS_AST=1 skip promotion."""

    def test_node_backend_without_flag_no_promotion(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv("FORGE_TS_AST", raising=False)
        baseline = "const RATE_LIMIT = 120\n"
        edited = "const RATE_LIMIT = 60\n"
        meta = _scaffold_block_project(
            tmp_path,
            baseline_body=baseline,
            edited_body=edited,
            language=BackendLanguage.NODE,
        )
        ctx = _mk_ctx(
            tmp_path,
            block_key=meta["block_key"],
            baseline_sha=meta["baseline_sha"],
            feature_key=meta["feature_key"],
            language=BackendLanguage.NODE,
        )
        plan = _mk_plan(meta)

        patches = InjectionExtractor().extract(ctx, plan)
        assert len(patches) == 1
        assert patches[0].risk == "safe-apply"
        # TypeScript path is opt-in; without FORGE_TS_AST=1 it returns ().
        assert patches[0].option_promotion == ()


# ---------------------------------------------------------------------------
# Bundle emission tests
# ---------------------------------------------------------------------------


class TestOptionPromoteBundleEmission:
    """The bundle writes a NNNN-option-promote-<safe_key>.patch side-car."""

    def test_option_promote_file_emitted_next_to_main_patch(self, tmp_path: Path) -> None:
        baseline = "RATE_LIMIT = 120\n"
        edited = "RATE_LIMIT = 60\n"
        meta = _scaffold_block_project(tmp_path, baseline_body=baseline, edited_body=edited)
        ctx = _mk_ctx(
            tmp_path,
            block_key=meta["block_key"],
            baseline_sha=meta["baseline_sha"],
            feature_key=meta["feature_key"],
        )
        patches = InjectionExtractor().extract(ctx, _mk_plan(meta))
        assert len(patches) == 1
        assert patches[0].option_promotion

        bundle = HarvestBundle(
            bundle_id="harvest-test",
            project_root=tmp_path,
            forge_version="0.0.0+test",
            candidates=patches,
        )
        out_dir = tmp_path / "bundle"
        write_bundle(bundle, out_dir)

        # The fragment dir carries both the main patch + the option-promote
        # side-car under the same NNNN index (0001).
        frag_dir = out_dir / "patches" / meta["feature_key"]
        main_patches = sorted(frag_dir.glob("0001-block-*.patch"))
        promote_patches = sorted(frag_dir.glob("0001-option-promote-*.patch"))
        assert len(main_patches) == 1
        assert len(promote_patches) == 1
        body = promote_patches[0].read_text(encoding="utf-8")
        # The body carries the proposed Option declaration and the
        # inject.yaml diff substituting the literal for an interpolation.
        assert "Option-promotion suggestion" in body
        assert "Option(" in body
        assert "OptionType.INT" in body
        assert "120" in body  # old literal value referenced in diff.

    def test_no_promote_file_when_payload_empty(self, tmp_path: Path) -> None:
        # Structural edit → no option_promotion payload → no side-car.
        baseline = "x = 1\n"
        edited = "x = 1\ny = 2\n"
        meta = _scaffold_block_project(tmp_path, baseline_body=baseline, edited_body=edited)
        ctx = _mk_ctx(
            tmp_path,
            block_key=meta["block_key"],
            baseline_sha=meta["baseline_sha"],
            feature_key=meta["feature_key"],
        )
        patches = InjectionExtractor().extract(ctx, _mk_plan(meta))
        assert len(patches) == 1
        assert patches[0].option_promotion == ()

        bundle = HarvestBundle(
            bundle_id="harvest-test",
            project_root=tmp_path,
            forge_version="0.0.0+test",
            candidates=patches,
        )
        out_dir = tmp_path / "bundle"
        write_bundle(bundle, out_dir)
        frag_dir = out_dir / "patches" / meta["feature_key"]
        promote_patches = list(frag_dir.glob("*option-promote*"))
        assert promote_patches == []


# ---------------------------------------------------------------------------
# Telemetry tests
# ---------------------------------------------------------------------------


class TestOptionPromotionTelemetry:
    """``harvest.option_promotion_suggested`` events fire per LiteralEdit."""

    def test_telemetry_emits_one_event_per_literal(self, tmp_path: Path) -> None:
        # Configure local telemetry sink to capture events.
        sink_path = tmp_path / "telemetry.jsonl"
        telemetry.configure(
            telemetry.TelemetryConfig(mode="local", fields="full", sink_path=sink_path)
        )
        try:
            baseline = "RATE_LIMIT = 120\n"
            edited = "RATE_LIMIT = 60\n"
            meta = _scaffold_block_project(tmp_path, baseline_body=baseline, edited_body=edited)
            ctx = _mk_ctx(
                tmp_path,
                block_key=meta["block_key"],
                baseline_sha=meta["baseline_sha"],
                feature_key=meta["feature_key"],
            )
            patches = InjectionExtractor().extract(ctx, _mk_plan(meta))
            assert patches[0].option_promotion  # precondition

            bundle = HarvestBundle(
                bundle_id="harvest-test",
                project_root=tmp_path,
                forge_version="0.0.0+test",
                candidates=patches,
            )
            # Invoke the harvest CLI's telemetry helper directly so the
            # test doesn't depend on the dispatcher's full plumbing.
            from forge.cli.commands.harvest import _emit_harvest_telemetry

            _emit_harvest_telemetry(tmp_path, bundle)
            telemetry.shutdown(wait=True)

            events = [
                json.loads(line) for line in sink_path.read_text(encoding="utf-8").splitlines()
            ]
            promotion_events = [
                e
                for e in events
                if e.get("event") == telemetry.EVENT_HARVEST_OPTION_PROMOTION_SUGGESTED
            ]
            assert len(promotion_events) == 1
            ev = promotion_events[0]
            assert ev["kind"] == "int"
            assert ev["value"] == "60"
            assert ev["fragment"] == meta["feature_key"]
        finally:
            telemetry.configure(telemetry.TelemetryConfig())

    def test_telemetry_no_event_when_promotion_empty(self, tmp_path: Path) -> None:
        sink_path = tmp_path / "telemetry.jsonl"
        telemetry.configure(
            telemetry.TelemetryConfig(mode="local", fields="full", sink_path=sink_path)
        )
        try:
            baseline = "x = 1\n"
            edited = "x = 1\ny = 2\n"  # structural — no promotion
            meta = _scaffold_block_project(tmp_path, baseline_body=baseline, edited_body=edited)
            ctx = _mk_ctx(
                tmp_path,
                block_key=meta["block_key"],
                baseline_sha=meta["baseline_sha"],
                feature_key=meta["feature_key"],
            )
            patches = InjectionExtractor().extract(ctx, _mk_plan(meta))
            assert patches[0].option_promotion == ()

            bundle = HarvestBundle(
                bundle_id="harvest-test",
                project_root=tmp_path,
                forge_version="0.0.0+test",
                candidates=patches,
            )
            from forge.cli.commands.harvest import _emit_harvest_telemetry

            _emit_harvest_telemetry(tmp_path, bundle)
            telemetry.shutdown(wait=True)

            if sink_path.exists():
                events = [
                    json.loads(line) for line in sink_path.read_text(encoding="utf-8").splitlines()
                ]
            else:
                events = []
            promotion_events = [
                e
                for e in events
                if e.get("event") == telemetry.EVENT_HARVEST_OPTION_PROMOTION_SUGGESTED
            ]
            assert promotion_events == []
        finally:
            telemetry.configure(telemetry.TelemetryConfig())
