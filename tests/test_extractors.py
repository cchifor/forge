"""Phase 3: extractors framework scaffolding.

These tests cover the wiring contract:

* :class:`forge.extractors.pipeline.ExtractorPipeline` runs every
  registered extractor and aggregates their candidate-patch lists.
* The four built-in extractors return ``[]`` (Phase 3 stub guarantee).
* :class:`forge.extractors.pipeline.CandidatePatch` and
  :class:`forge.extractors.plan.ExtractionPlan` are frozen dataclasses
  that hash + compare by value.

Phase 4 will add tests for actual extraction logic; this file only
verifies the framework scaffolding.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from forge.config import BackendConfig, BackendLanguage
from forge.extractors import (
    CandidatePatch,
    DepsExtractor,
    EnvExtractor,
    ExtractionPlan,
    ExtractorPipeline,
    FileExtractor,
    InjectionExtractor,
)
from forge.fragment_context import FragmentContext


def _mk_ctx(tmp_path: Path) -> FragmentContext:
    return FragmentContext(
        backend_config=BackendConfig(
            name="api",
            project_name="p",
            language=BackendLanguage.PYTHON,
        ),
        backend_dir=tmp_path,
        project_root=tmp_path,
        options={},
        provenance=None,
    )


def _empty_plan() -> ExtractionPlan:
    return ExtractionPlan(
        fragment_name="frag-x",
        files=(),
        injections=(),
        dependencies=(),
        env_vars=(),
    )


class TestExtractionPlan:
    def test_is_frozen(self) -> None:
        plan = _empty_plan()
        with pytest.raises(FrozenInstanceError):
            plan.fragment_name = "mutated"  # type: ignore[misc]

    def test_is_hashable(self) -> None:
        plan_a = _empty_plan()
        plan_b = _empty_plan()
        assert hash(plan_a) == hash(plan_b)
        assert plan_a == plan_b

    def test_carries_search_targets_verbatim(self) -> None:
        plan = ExtractionPlan(
            fragment_name="frag",
            files=(("src/a.py", "app/a.py"),),
            injections=("inj_record_placeholder",),
            dependencies=("slowapi>=0.1.9",),
            env_vars=(("FOO", "bar"),),
        )
        assert plan.files == (("src/a.py", "app/a.py"),)
        assert plan.injections == ("inj_record_placeholder",)
        assert plan.dependencies == ("slowapi>=0.1.9",)
        assert plan.env_vars == (("FOO", "bar"),)


class TestCandidatePatch:
    def _mk_patch(self, **overrides: object) -> CandidatePatch:
        defaults: dict[str, object] = dict(
            fragment="frag",
            backend="api",
            kind="files",
            rel_path="app/a.py",
            target_path="/tmp/proj/app/a.py",
            diff="@@ -1,1 +1,1 @@\n-old\n+new\n",
            baseline_sha="abc",
            current_sha="def",
            risk="safe-apply",
        )
        defaults.update(overrides)
        return CandidatePatch(**defaults)  # type: ignore[arg-type]

    def test_is_frozen(self) -> None:
        patch = self._mk_patch()
        with pytest.raises(FrozenInstanceError):
            patch.diff = "mutated"  # type: ignore[misc]

    def test_is_hashable(self) -> None:
        a = self._mk_patch()
        b = self._mk_patch()
        assert hash(a) == hash(b)
        assert a == b
        # Can be placed in a set — pipeline callers de-dupe by identity.
        assert {a, b} == {a}

    def test_rationale_defaults_to_empty(self) -> None:
        patch = self._mk_patch()
        assert patch.rationale == ""

    def test_none_baseline_is_allowed_for_pre_1_1_targets(self) -> None:
        patch = self._mk_patch(baseline_sha=None, risk="needs-review")
        assert patch.baseline_sha is None


class TestBuiltinStubsReturnEmpty:
    """Phase 3 guarantee: every built-in extractor is a no-op."""

    def test_file_extractor_returns_empty(self, tmp_path: Path) -> None:
        assert FileExtractor().extract(_mk_ctx(tmp_path), _empty_plan()) == []

    def test_injection_extractor_returns_empty(self, tmp_path: Path) -> None:
        assert InjectionExtractor().extract(_mk_ctx(tmp_path), _empty_plan()) == []

    def test_deps_extractor_returns_empty(self, tmp_path: Path) -> None:
        assert DepsExtractor().extract(_mk_ctx(tmp_path), _empty_plan()) == []

    def test_env_extractor_returns_empty(self, tmp_path: Path) -> None:
        assert EnvExtractor().extract(_mk_ctx(tmp_path), _empty_plan()) == []

    def test_kinds_are_canonical(self) -> None:
        # The 4 kinds drive plugin-side overrides via
        # ForgeAPI.add_extractor; locking them down here prevents a
        # silent rename from breaking plugin compatibility.
        assert FileExtractor.kind == "files"
        assert InjectionExtractor.kind == "block"
        assert DepsExtractor.kind == "deps"
        assert EnvExtractor.kind == "env"


class TestExtractorPipeline:
    def test_default_pipeline_has_four_builtin_extractors(self) -> None:
        pipeline = ExtractorPipeline.default()
        kinds = tuple(e.kind for e in pipeline.extractors)
        assert kinds == ("files", "block", "deps", "env")

    def test_default_pipeline_aggregates_empty_lists(self, tmp_path: Path) -> None:
        pipeline = ExtractorPipeline.default()
        out = pipeline.run(_mk_ctx(tmp_path), _empty_plan())
        assert out == []

    def test_pipeline_aggregates_results_from_every_extractor(self, tmp_path: Path) -> None:
        # Drop in a tuple of spies that each emit one CandidatePatch so
        # we can verify the pipeline concatenates rather than e.g.
        # short-circuiting on the first non-empty result.

        log: list[str] = []

        class _Spy:
            def __init__(self, name: str) -> None:
                self.kind = name
                self._name = name

            def extract(self, ctx: FragmentContext, plan: ExtractionPlan) -> list[CandidatePatch]:
                log.append(self._name)
                return [
                    CandidatePatch(
                        fragment=plan.fragment_name,
                        backend="api",
                        kind=self._name,
                        rel_path=f"{self._name}.txt",
                        target_path=str(ctx.backend_dir / f"{self._name}.txt"),
                        diff="",
                        baseline_sha=None,
                        current_sha="x",
                        risk="needs-review",
                    )
                ]

        pipeline = ExtractorPipeline(
            extractors=(_Spy("files"), _Spy("block"), _Spy("deps"), _Spy("env")),
        )
        out = pipeline.run(_mk_ctx(tmp_path), _empty_plan())
        assert log == ["files", "block", "deps", "env"]
        assert [p.kind for p in out] == ["files", "block", "deps", "env"]

    def test_pipeline_with_no_extractors_returns_empty(self, tmp_path: Path) -> None:
        pipeline = ExtractorPipeline()
        assert pipeline.run(_mk_ctx(tmp_path), _empty_plan()) == []
