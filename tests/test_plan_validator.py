"""Tests for pre-generation plan validation (P1.3)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from forge.capability_resolver import ResolvedFragment, ResolvedPlan
from forge.config import BackendLanguage
from forge.fragments import Fragment, FragmentImplSpec
from forge.plan_validator import PlanValidationError, validate_plan


def _make_fragment(tmp_path: Path, name: str, impl_dir: str) -> ResolvedFragment:
    frag_root = tmp_path / impl_dir
    frag_root.mkdir(parents=True, exist_ok=True)
    fragment = Fragment(
        name=name,
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(fragment_dir=str(frag_root))
        },
    )
    return ResolvedFragment(
        fragment=fragment,
        target_backends=(BackendLanguage.PYTHON,),
    )


def _plan(*fragments: ResolvedFragment) -> ResolvedPlan:
    return ResolvedPlan(
        ordered=fragments,
        capabilities=frozenset(),
        option_values={},
    )


class TestMissingFragmentDirectory:
    def test_missing_directory_raises(self, tmp_path: Path) -> None:
        fragment = Fragment(
            name="ghost",
            implementations={
                BackendLanguage.PYTHON: FragmentImplSpec(
                    fragment_dir=str(tmp_path / "never_existed")
                )
            },
        )
        plan = _plan(
            ResolvedFragment(fragment=fragment, target_backends=(BackendLanguage.PYTHON,))
        )
        with pytest.raises(PlanValidationError) as exc:
            validate_plan(plan)
        assert "does not exist" in str(exc.value)


class TestInjectYamlValidation:
    def test_missing_file_is_fine(self, tmp_path: Path) -> None:
        frag = _make_fragment(tmp_path, "no_inject", "frags/no_inject")
        validate_plan(_plan(frag))

    def test_malformed_yaml_raises(self, tmp_path: Path) -> None:
        frag = _make_fragment(tmp_path, "bad_yaml", "frags/bad_yaml")
        inject = tmp_path / "frags/bad_yaml/inject.yaml"
        inject.write_text(": :: : not yaml", encoding="utf-8")
        with pytest.raises(PlanValidationError) as exc:
            validate_plan(_plan(frag))
        assert "failed to parse" in str(exc.value)

    def test_top_level_not_list_raises(self, tmp_path: Path) -> None:
        frag = _make_fragment(tmp_path, "dict_at_top", "frags/dict_at_top")
        inject = tmp_path / "frags/dict_at_top/inject.yaml"
        inject.write_text(yaml.safe_dump({"foo": "bar"}), encoding="utf-8")
        with pytest.raises(PlanValidationError) as exc:
            validate_plan(_plan(frag))
        assert "must be a list" in str(exc.value)

    def test_missing_required_key_raises(self, tmp_path: Path) -> None:
        frag = _make_fragment(tmp_path, "missing_target", "frags/missing_target")
        inject = tmp_path / "frags/missing_target/inject.yaml"
        inject.write_text(
            yaml.safe_dump([{"marker": "FORGE:X", "snippet": "x"}]),
            encoding="utf-8",
        )
        with pytest.raises(PlanValidationError) as exc:
            validate_plan(_plan(frag))
        assert "missing required key 'target'" in str(exc.value)

    def test_invalid_position_raises(self, tmp_path: Path) -> None:
        frag = _make_fragment(tmp_path, "bad_position", "frags/bad_position")
        inject = tmp_path / "frags/bad_position/inject.yaml"
        inject.write_text(
            yaml.safe_dump([
                {"target": "a", "marker": "FORGE:X", "snippet": "x", "position": "sideways"}
            ]),
            encoding="utf-8",
        )
        with pytest.raises(PlanValidationError) as exc:
            validate_plan(_plan(frag))
        assert "position must be" in str(exc.value)

    def test_valid_inject_yaml_passes(self, tmp_path: Path) -> None:
        frag = _make_fragment(tmp_path, "good_inject", "frags/good_inject")
        inject = tmp_path / "frags/good_inject/inject.yaml"
        inject.write_text(
            yaml.safe_dump([
                {"target": "src/app.py", "marker": "FORGE:X", "snippet": "x"},
                {
                    "target": "src/app.py",
                    "marker": "FORGE:Y",
                    "snippet": "y",
                    "position": "before",
                },
            ]),
            encoding="utf-8",
        )
        validate_plan(_plan(frag))


class TestEnvYamlValidation:
    def test_malformed_env_yaml_raises(self, tmp_path: Path) -> None:
        frag = _make_fragment(tmp_path, "bad_env", "frags/bad_env")
        (tmp_path / "frags/bad_env/env.yaml").write_text(": :: bad", encoding="utf-8")
        with pytest.raises(PlanValidationError) as exc:
            validate_plan(_plan(frag))
        assert "env.yaml failed to parse" in str(exc.value)

    def test_top_level_not_mapping_raises(self, tmp_path: Path) -> None:
        frag = _make_fragment(tmp_path, "list_env", "frags/list_env")
        (tmp_path / "frags/list_env/env.yaml").write_text(
            yaml.safe_dump(["A=1"]), encoding="utf-8"
        )
        with pytest.raises(PlanValidationError) as exc:
            validate_plan(_plan(frag))
        assert "must be a mapping" in str(exc.value)


class TestFileOverlap:
    def test_single_fragment_file_is_fine(self, tmp_path: Path) -> None:
        frag = _make_fragment(tmp_path, "single", "frags/single")
        files = tmp_path / "frags/single/files/src"
        files.mkdir(parents=True)
        (files / "a.py").write_text("x")
        validate_plan(_plan(frag))

    def test_two_fragments_overlapping_file_raises(self, tmp_path: Path) -> None:
        frag_a = _make_fragment(tmp_path, "alpha", "frags/alpha")
        frag_b = _make_fragment(tmp_path, "beta", "frags/beta")
        for name in ("alpha", "beta"):
            f = tmp_path / f"frags/{name}/files/src"
            f.mkdir(parents=True)
            (f / "shared.py").write_text("x")
        with pytest.raises(PlanValidationError) as exc:
            validate_plan(_plan(frag_a, frag_b))
        assert "overlaps with fragment" in str(exc.value)


class TestAggregation:
    def test_reports_multiple_issues_together(self, tmp_path: Path) -> None:
        frag_a = _make_fragment(tmp_path, "alpha", "frags/alpha")
        (tmp_path / "frags/alpha/inject.yaml").write_text(
            yaml.safe_dump({"not": "a list"}), encoding="utf-8"
        )
        (tmp_path / "frags/alpha/env.yaml").write_text(
            yaml.safe_dump(["not", "a", "mapping"]), encoding="utf-8"
        )
        with pytest.raises(PlanValidationError) as exc:
            validate_plan(_plan(frag_a))
        msg = str(exc.value)
        assert "inject.yaml" in msg
        assert "env.yaml" in msg
