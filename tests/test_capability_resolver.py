"""Tests for capability_resolver: defaults, topo sort, conflicts, backend filtering."""

from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import patch

import pytest

from forge.capability_resolver import resolve
from forge.config import BackendConfig, BackendLanguage, ProjectConfig
from forge.errors import GeneratorError
from forge.features import FeatureConfig, FeatureSpec, FragmentImplSpec


def _project(langs: list[BackendLanguage], features: dict[str, FeatureConfig] | None = None) -> ProjectConfig:
    backends = [
        BackendConfig(name=f"svc-{i}", project_name="P", language=lang, server_port=5000 + i)
        for i, lang in enumerate(langs)
    ]
    return ProjectConfig(
        project_name="P",
        backends=backends,
        frontend=None,
        features=features or {},
    )


def _mk_spec(key: str, **kw) -> FeatureSpec:
    defaults = dict(
        key=key,
        display_label=key,
        cli_flag=f"--include-{key}",
        implementations={BackendLanguage.PYTHON: FragmentImplSpec(fragment_dir=f"{key}/python")},
    )
    defaults.update(kw)
    return FeatureSpec(**defaults)


@pytest.fixture
def empty_registry() -> Iterator[dict]:
    """Swap FEATURE_REGISTRY for a clean dict so tests can register fake features."""
    fake: dict = {}
    with patch("forge.capability_resolver.FEATURE_REGISTRY", fake), patch(
        "forge.features.FEATURE_REGISTRY", fake
    ):
        yield fake


class TestAlwaysOnDefaults:
    def test_always_on_feature_enabled_with_no_user_input(self, empty_registry) -> None:
        empty_registry["corr"] = _mk_spec("corr", always_on=True)
        plan = resolve(_project([BackendLanguage.PYTHON]))
        assert [f.spec.key for f in plan.ordered] == ["corr"]

    def test_default_enabled_feature_enabled_by_default(self, empty_registry) -> None:
        empty_registry["def"] = _mk_spec("def", default_enabled=True)
        plan = resolve(_project([BackendLanguage.PYTHON]))
        assert [f.spec.key for f in plan.ordered] == ["def"]

    def test_default_disabled_feature_stays_off(self, empty_registry) -> None:
        empty_registry["off"] = _mk_spec("off")
        plan = resolve(_project([BackendLanguage.PYTHON]))
        assert plan.ordered == ()


class TestTopoSort:
    def test_dependency_ordered_before_dependent(self, empty_registry) -> None:
        empty_registry["base"] = _mk_spec("base")
        empty_registry["built_on_base"] = _mk_spec("built_on_base", depends_on=("base",))
        plan = resolve(
            _project(
                [BackendLanguage.PYTHON],
                {"base": FeatureConfig(enabled=True), "built_on_base": FeatureConfig(enabled=True)},
            )
        )
        keys = [f.spec.key for f in plan.ordered]
        assert keys.index("base") < keys.index("built_on_base")

    def test_missing_dependency_raises(self, empty_registry) -> None:
        empty_registry["needs_x"] = _mk_spec("needs_x", depends_on=("x",))
        with pytest.raises(GeneratorError, match="requires 'x'"):
            resolve(
                _project(
                    [BackendLanguage.PYTHON],
                    {"needs_x": FeatureConfig(enabled=True)},
                )
            )

    def test_cycle_detected(self, empty_registry) -> None:
        empty_registry["a"] = _mk_spec("a", depends_on=("b",))
        empty_registry["b"] = _mk_spec("b", depends_on=("a",))
        with pytest.raises(GeneratorError, match="[Cc]yclic"):
            resolve(
                _project(
                    [BackendLanguage.PYTHON],
                    {"a": FeatureConfig(enabled=True), "b": FeatureConfig(enabled=True)},
                )
            )


class TestConflicts:
    def test_two_conflicting_raises(self, empty_registry) -> None:
        empty_registry["x"] = _mk_spec("x", conflicts_with=("y",))
        empty_registry["y"] = _mk_spec("y", conflicts_with=("x",))
        with pytest.raises(GeneratorError, match="conflict"):
            resolve(
                _project(
                    [BackendLanguage.PYTHON],
                    {"x": FeatureConfig(enabled=True), "y": FeatureConfig(enabled=True)},
                )
            )


class TestCapabilities:
    def test_capabilities_deduped(self, empty_registry) -> None:
        empty_registry["a"] = _mk_spec("a", capabilities=("redis",))
        empty_registry["b"] = _mk_spec("b", capabilities=("redis", "postgres-pgvector"))
        plan = resolve(
            _project(
                [BackendLanguage.PYTHON],
                {"a": FeatureConfig(enabled=True), "b": FeatureConfig(enabled=True)},
            )
        )
        assert plan.capabilities == frozenset({"redis", "postgres-pgvector"})


class TestBackendCompatibility:
    def test_unsupported_backend_raises_when_user_requested(self, empty_registry) -> None:
        empty_registry["rust_only"] = _mk_spec(
            "rust_only",
            implementations={BackendLanguage.RUST: FragmentImplSpec(fragment_dir="r")},
        )
        with pytest.raises(GeneratorError, match="supported backends"):
            resolve(
                _project(
                    [BackendLanguage.PYTHON],
                    {"rust_only": FeatureConfig(enabled=True)},
                )
            )

    def test_always_on_with_no_matching_backend_skips_silently(self, empty_registry) -> None:
        # A Python-only always_on feature should not block a Rust-only project.
        empty_registry["py_only"] = _mk_spec(
            "py_only",
            always_on=True,
            implementations={BackendLanguage.PYTHON: FragmentImplSpec(fragment_dir="p")},
        )
        plan = resolve(_project([BackendLanguage.RUST]))
        assert plan.ordered == ()

    def test_default_enabled_without_matching_backend_skips_silently(self, empty_registry) -> None:
        # default_enabled without user opt-in also skips when backend missing.
        empty_registry["py_only"] = _mk_spec(
            "py_only",
            default_enabled=True,
            implementations={BackendLanguage.PYTHON: FragmentImplSpec(fragment_dir="p")},
        )
        plan = resolve(_project([BackendLanguage.RUST]))
        assert plan.ordered == ()

    def test_unknown_feature_key_raises(self, empty_registry) -> None:
        with pytest.raises(GeneratorError, match="Unknown feature 'nope'"):
            resolve(
                _project(
                    [BackendLanguage.PYTHON],
                    {"nope": FeatureConfig(enabled=True)},
                )
            )

    def test_target_backends_preserves_project_order(self, empty_registry) -> None:
        empty_registry["poly"] = _mk_spec(
            "poly",
            implementations={
                BackendLanguage.PYTHON: FragmentImplSpec(fragment_dir="p"),
                BackendLanguage.RUST: FragmentImplSpec(fragment_dir="r"),
            },
        )
        plan = resolve(
            _project(
                [BackendLanguage.RUST, BackendLanguage.PYTHON],
                {"poly": FeatureConfig(enabled=True)},
            )
        )
        assert plan.ordered[0].target_backends == (BackendLanguage.RUST, BackendLanguage.PYTHON)
