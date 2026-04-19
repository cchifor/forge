"""Tests for capability_resolver: defaults, topo sort, conflicts, backend filtering."""

from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import patch

import pytest

from forge.capability_resolver import resolve
from forge.config import BackendConfig, BackendLanguage, ProjectConfig
from forge.errors import GeneratorError
from forge.fragments import Fragment, FragmentImplSpec
from forge.options import FeatureCategory, Option, OptionType


def _project(
    langs: list[BackendLanguage], options: dict[str, object] | None = None
) -> ProjectConfig:
    backends = [
        BackendConfig(name=f"svc-{i}", project_name="P", language=lang, server_port=5000 + i)
        for i, lang in enumerate(langs)
    ]
    return ProjectConfig(
        project_name="P",
        backends=backends,
        frontend=None,
        options=options or {},
    )


def _mk_fragment(name: str, **kw) -> Fragment:
    defaults = dict(
        name=name,
        implementations={BackendLanguage.PYTHON: FragmentImplSpec(fragment_dir=f"{name}/python")},
    )
    defaults.update(kw)
    return Fragment(**defaults)


def _mk_option(path: str, *, fragments: tuple[str, ...], default: bool = False) -> Option:
    return Option(
        path=path,
        type=OptionType.BOOL,
        default=default,
        summary=path,
        description=path,
        category=FeatureCategory.PLATFORM,
        enables={True: fragments},
    )


@pytest.fixture
def isolated_registries() -> Iterator[tuple[dict, dict]]:
    """Swap both OPTION_REGISTRY and FRAGMENT_REGISTRY for empty dicts.

    Tests can register their own fakes without touching the real
    catalogue. Patched at every import site so the resolver sees the
    same empty dict the test populated.
    """
    options: dict = {}
    fragments: dict = {}
    with (
        patch("forge.capability_resolver.OPTION_REGISTRY", options),
        patch("forge.options.OPTION_REGISTRY", options),
        patch("forge.capability_resolver.FRAGMENT_REGISTRY", fragments),
        patch("forge.fragments.FRAGMENT_REGISTRY", fragments),
        patch("forge.config.OPTION_REGISTRY", options, create=True),
    ):
        yield options, fragments


class TestDefaults:
    def test_default_true_option_enables_fragment_without_user_input(
        self, isolated_registries
    ) -> None:
        options, fragments = isolated_registries
        fragments["corr"] = _mk_fragment("corr")
        options["corr.always_on"] = _mk_option("corr.always_on", fragments=("corr",), default=True)
        plan = resolve(_project([BackendLanguage.PYTHON]))
        assert [rf.fragment.name for rf in plan.ordered] == ["corr"]

    def test_default_false_option_stays_off(self, isolated_registries) -> None:
        options, fragments = isolated_registries
        fragments["off"] = _mk_fragment("off")
        options["off.toggle"] = _mk_option("off.toggle", fragments=("off",), default=False)
        plan = resolve(_project([BackendLanguage.PYTHON]))
        assert plan.ordered == ()

    def test_user_set_true_enables_fragment(self, isolated_registries) -> None:
        options, fragments = isolated_registries
        fragments["x"] = _mk_fragment("x")
        options["x.on"] = _mk_option("x.on", fragments=("x",), default=False)
        plan = resolve(_project([BackendLanguage.PYTHON], {"x.on": True}))
        assert [rf.fragment.name for rf in plan.ordered] == ["x"]


class TestTopoSort:
    def test_dependency_ordered_before_dependent(self, isolated_registries) -> None:
        options, fragments = isolated_registries
        fragments["base"] = _mk_fragment("base")
        fragments["built_on_base"] = _mk_fragment("built_on_base", depends_on=("base",))
        options["a.base"] = _mk_option("a.base", fragments=("base",), default=True)
        options["a.built"] = _mk_option("a.built", fragments=("built_on_base",), default=True)
        plan = resolve(_project([BackendLanguage.PYTHON]))
        names = [rf.fragment.name for rf in plan.ordered]
        assert names.index("base") < names.index("built_on_base")

    def test_transitive_dependency_auto_included(self, isolated_registries) -> None:
        """A fragment's depends_on is auto-pulled; user doesn't opt in explicitly."""
        options, fragments = isolated_registries
        fragments["base"] = _mk_fragment("base")
        fragments["dependent"] = _mk_fragment("dependent", depends_on=("base",))
        options["a.on"] = _mk_option("a.on", fragments=("dependent",), default=True)
        plan = resolve(_project([BackendLanguage.PYTHON]))
        names = [rf.fragment.name for rf in plan.ordered]
        assert "base" in names
        assert "dependent" in names
        assert names.index("base") < names.index("dependent")

    def test_cycle_detected(self, isolated_registries) -> None:
        options, fragments = isolated_registries
        fragments["a"] = _mk_fragment("a", depends_on=("b",))
        fragments["b"] = _mk_fragment("b", depends_on=("a",))
        options["t.on"] = _mk_option("t.on", fragments=("a", "b"), default=True)
        with pytest.raises(GeneratorError, match="[Cc]yclic"):
            resolve(_project([BackendLanguage.PYTHON]))


class TestConflicts:
    def test_two_conflicting_raises(self, isolated_registries) -> None:
        options, fragments = isolated_registries
        fragments["x"] = _mk_fragment("x", conflicts_with=("y",))
        fragments["y"] = _mk_fragment("y", conflicts_with=("x",))
        options["a.on"] = _mk_option("a.on", fragments=("x", "y"), default=True)
        with pytest.raises(GeneratorError, match="conflict"):
            resolve(_project([BackendLanguage.PYTHON]))


class TestCapabilities:
    def test_capabilities_deduped(self, isolated_registries) -> None:
        options, fragments = isolated_registries
        fragments["a"] = _mk_fragment("a", capabilities=("redis",))
        fragments["b"] = _mk_fragment("b", capabilities=("redis", "postgres-pgvector"))
        options["p.a"] = _mk_option("p.a", fragments=("a",), default=True)
        options["p.b"] = _mk_option("p.b", fragments=("b",), default=True)
        plan = resolve(_project([BackendLanguage.PYTHON]))
        assert plan.capabilities == frozenset({"redis", "postgres-pgvector"})


class TestBackendCompatibility:
    def test_unsupported_backend_raises_when_user_requested(self, isolated_registries) -> None:
        options, fragments = isolated_registries
        fragments["rust_only"] = _mk_fragment(
            "rust_only",
            implementations={BackendLanguage.RUST: FragmentImplSpec(fragment_dir="r")},
        )
        options["p.on"] = _mk_option("p.on", fragments=("rust_only",), default=False)
        with pytest.raises(GeneratorError, match="supported backends"):
            resolve(_project([BackendLanguage.PYTHON], {"p.on": True}))

    def test_default_with_no_matching_backend_skips_silently(self, isolated_registries) -> None:
        """A Python-only fragment selected by a default value must skip on a Rust project."""
        options, fragments = isolated_registries
        fragments["py_only"] = _mk_fragment(
            "py_only",
            implementations={BackendLanguage.PYTHON: FragmentImplSpec(fragment_dir="p")},
        )
        options["p.on"] = _mk_option("p.on", fragments=("py_only",), default=True)
        plan = resolve(_project([BackendLanguage.RUST]))
        assert plan.ordered == ()

    def test_unknown_option_path_raises(self, isolated_registries) -> None:
        """Unknown paths in config.options are caught by the resolver."""
        # Fixture keeps OPTION_REGISTRY empty — any path is "unknown".
        _ = isolated_registries
        with pytest.raises(GeneratorError, match="Unknown option"):
            resolve(_project([BackendLanguage.PYTHON], {"nope.nada": True}))

    def test_target_backends_preserves_project_order(self, isolated_registries) -> None:
        options, fragments = isolated_registries
        fragments["poly"] = _mk_fragment(
            "poly",
            implementations={
                BackendLanguage.PYTHON: FragmentImplSpec(fragment_dir="p"),
                BackendLanguage.RUST: FragmentImplSpec(fragment_dir="r"),
            },
        )
        options["p.on"] = _mk_option("p.on", fragments=("poly",), default=True)
        plan = resolve(_project([BackendLanguage.RUST, BackendLanguage.PYTHON]))
        assert plan.ordered[0].target_backends == (BackendLanguage.RUST, BackendLanguage.PYTHON)
