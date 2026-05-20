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


# ---------------------------------------------------------------------------
# Initiative #1 — typed port: ``_Injection`` enforces zone / position
# invariants at construction so a non-YAML caller (middleware_spec.render_*,
# future plugin extractors, …) can't smuggle in a bad literal that only
# fails later in the dispatch loop.
# ---------------------------------------------------------------------------


class TestInjectionTypedPort:
    """Construction-time invariants for :class:`forge.appliers.plan._Injection`.

    The YAML loader pre-validates with richer path/index context, so these
    tests target the Python construction path (the only one a typo-ed
    middleware renderer or plugin extractor would hit).
    """

    def _kwargs(self, **overrides):
        base = dict(
            feature_key="demo",
            target="main.py",
            marker="FORGE:DEMO",
            snippet="x = 1",
        )
        base.update(overrides)
        return base

    def test_default_position_and_zone_construct_cleanly(self) -> None:
        from forge.appliers.plan import _Injection  # noqa: PLC0415

        inj = _Injection(**self._kwargs())
        assert inj.position == "after"
        assert inj.zone == "generated"

    def test_invalid_position_raises_fragment_error(self) -> None:
        from forge.appliers.plan import _Injection  # noqa: PLC0415
        from forge.errors import FRAGMENT_INJECT_YAML_BAD_POSITION

        with pytest.raises(FragmentError) as exc:
            _Injection(**self._kwargs(position="sideways"))
        assert exc.value.code == FRAGMENT_INJECT_YAML_BAD_POSITION
        assert "sideways" in str(exc.value)

    def test_invalid_zone_raises_fragment_error(self) -> None:
        from forge.appliers.plan import _Injection  # noqa: PLC0415
        from forge.errors import FRAGMENT_INJECT_YAML_BAD_ZONE

        with pytest.raises(FragmentError) as exc:
            _Injection(**self._kwargs(zone="garbage"))
        assert exc.value.code == FRAGMENT_INJECT_YAML_BAD_ZONE
        assert "garbage" in str(exc.value)

    def test_every_valid_position_and_zone_constructs(self) -> None:
        from forge.appliers.plan import (  # noqa: PLC0415
            INJECTION_POSITIONS,
            INJECTION_ZONES,
            _Injection,
        )

        for pos in INJECTION_POSITIONS:
            for zone in INJECTION_ZONES:
                inj = _Injection(**self._kwargs(position=pos, zone=zone))
                assert inj.position == pos
                assert inj.zone == zone
