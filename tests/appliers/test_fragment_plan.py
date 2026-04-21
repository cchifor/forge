"""Tests for ``FragmentPlan.from_impl`` — the resolution pass."""

from __future__ import annotations

from pathlib import Path

import pytest

from forge.appliers import FragmentPlan
from forge.errors import FRAGMENT_DIR_MISSING, FragmentError
from forge.fragments import FragmentImplSpec


class TestFromImpl:
    def test_raises_on_missing_fragment_dir(self, tmp_path: Path) -> None:
        impl = FragmentImplSpec(fragment_dir=str(tmp_path / "does" / "not" / "exist"))
        with pytest.raises(FragmentError) as excinfo:
            FragmentPlan.from_impl(impl, "nope")
        assert excinfo.value.code == FRAGMENT_DIR_MISSING

    def test_resolves_plan_with_only_files(self, tmp_path: Path) -> None:
        frag = tmp_path / "copy_only"
        (frag / "files").mkdir(parents=True)
        (frag / "files" / "hello.py").write_text("# hi\n", encoding="utf-8")

        impl = FragmentImplSpec(fragment_dir=str(frag))
        plan = FragmentPlan.from_impl(impl, "copy_only")

        assert plan.fragment_dir == frag
        assert plan.files_dir == frag / "files"
        assert plan.injections == ()
        assert plan.dependencies == ()
        assert plan.env_vars == ()
        assert plan.feature_key == "copy_only"

    def test_resolves_plan_with_inject_yaml(self, tmp_path: Path) -> None:
        frag = tmp_path / "inject_only"
        frag.mkdir()
        (frag / "inject.yaml").write_text(
            "- target: main.py\n"
            "  marker: FORGE:MIDDLEWARE\n"
            "  snippet: app.add_middleware(RateLimit)\n",
            encoding="utf-8",
        )

        impl = FragmentImplSpec(fragment_dir=str(frag))
        plan = FragmentPlan.from_impl(impl, "inject_only")

        assert plan.files_dir is None
        assert len(plan.injections) == 1
        assert plan.injections[0].target == "main.py"
        assert plan.injections[0].marker == "FORGE:MIDDLEWARE"

    def test_propagates_deps_and_env_from_impl(self, tmp_path: Path) -> None:
        frag = tmp_path / "deps_env"
        frag.mkdir()

        impl = FragmentImplSpec(
            fragment_dir=str(frag),
            dependencies=("slowapi>=0.1.9",),
            env_vars=(("RATE_LIMIT_PER_MINUTE", "60"),),
        )
        plan = FragmentPlan.from_impl(impl, "deps_env")

        assert plan.dependencies == ("slowapi>=0.1.9",)
        assert plan.env_vars == (("RATE_LIMIT_PER_MINUTE", "60"),)

    def test_jinja_render_applies_when_flagged(self, tmp_path: Path) -> None:
        frag = tmp_path / "rendered"
        frag.mkdir()
        (frag / "inject.yaml").write_text(
            "- target: main.py\n"
            "  marker: FORGE:TOP_K\n"
            "  render: true\n"
            "  snippet: 'TOP_K = {{ top_k }}'\n",
            encoding="utf-8",
        )

        impl = FragmentImplSpec(fragment_dir=str(frag))
        plan = FragmentPlan.from_impl(impl, "rendered", options={"top_k": 7})
        assert plan.injections[0].snippet == "TOP_K = 7"
