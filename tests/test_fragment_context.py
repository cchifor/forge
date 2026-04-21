"""Tests for Epic E's ``FragmentContext`` + ``reads_options`` plumbing."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from forge.capability_resolver import resolve
from forge.config import BackendConfig, BackendLanguage, ProjectConfig
from forge.errors import FragmentError, OptionsError
from forge.feature_injector import _load_injections, _render_snippet
from forge.fragment_context import FragmentContext
from forge.fragments import Fragment, FragmentImplSpec
from forge.options import FeatureCategory, Option, OptionType


def _mk_backend(language: BackendLanguage = BackendLanguage.PYTHON) -> BackendConfig:
    return BackendConfig(name="api", project_name="p", language=language)


# ---------------------------------------------------------------------------
# FragmentContext construction + filtering
# ---------------------------------------------------------------------------


class TestFragmentContext:
    def test_direct_construction_preserves_options_verbatim(self, tmp_path: Path) -> None:
        ctx = FragmentContext(
            backend_config=_mk_backend(),
            backend_dir=tmp_path,
            project_root=tmp_path.parent,
            options={"rag.top_k": 5, "agent.streaming": True},
            provenance=None,
            skip_existing_files=False,
        )
        assert ctx.options == {"rag.top_k": 5, "agent.streaming": True}
        assert ctx.backend_dir == tmp_path
        assert ctx.provenance is None

    def test_filtered_keeps_only_reads_options_paths(self, tmp_path: Path) -> None:
        ctx = FragmentContext.filtered(
            backend_config=_mk_backend(),
            backend_dir=tmp_path,
            project_root=tmp_path,
            option_values={
                "rag.top_k": 5,
                "rag.backend": "qdrant",
                "agent.streaming": True,
                "middleware.rate_limit": False,
            },
            reads_options=("rag.top_k", "agent.streaming"),
        )
        # Only declared paths appear; the fragment can't peek at
        # middleware.rate_limit or rag.backend.
        assert ctx.options == {"rag.top_k": 5, "agent.streaming": True}

    def test_filtered_drops_paths_absent_from_option_values(self, tmp_path: Path) -> None:
        ctx = FragmentContext.filtered(
            backend_config=_mk_backend(),
            backend_dir=tmp_path,
            project_root=tmp_path,
            option_values={"rag.top_k": 5},
            reads_options=("rag.top_k", "not_in_values"),
        )
        # Silent drop on absent — the resolver has already validated the
        # declared paths, so an absent one indicates a synthetic test
        # scenario we shouldn't fail noisily on.
        assert ctx.options == {"rag.top_k": 5}

    def test_filtered_with_empty_reads_options_yields_empty_view(self, tmp_path: Path) -> None:
        ctx = FragmentContext.filtered(
            backend_config=_mk_backend(),
            backend_dir=tmp_path,
            project_root=tmp_path,
            option_values={"rag.top_k": 5, "agent.streaming": True},
            reads_options=(),
        )
        # Pre-Epic-E behaviour preserved: a fragment that doesn't declare
        # reads_options sees nothing.
        assert ctx.options == {}

    def test_frozen_dataclass(self, tmp_path: Path) -> None:
        ctx = FragmentContext(
            backend_config=_mk_backend(),
            backend_dir=tmp_path,
            project_root=tmp_path,
            options={},
            provenance=None,
        )
        with pytest.raises(AttributeError):
            # frozen dataclass → FrozenInstanceError is a subclass of AttributeError
            ctx.options = {"bad": 1}  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Resolver: reads_options validation
# ---------------------------------------------------------------------------


def _isolated_registries(fragments: dict[str, Fragment], options: dict[str, Option]):
    """Context manager that patches both registries at every import site."""
    from contextlib import ExitStack

    stack = ExitStack()
    stack.enter_context(patch("forge.capability_resolver.OPTION_REGISTRY", options))
    stack.enter_context(patch("forge.options.OPTION_REGISTRY", options))
    stack.enter_context(patch("forge.capability_resolver.FRAGMENT_REGISTRY", fragments))
    stack.enter_context(patch("forge.fragments.FRAGMENT_REGISTRY", fragments))
    stack.enter_context(patch("forge.config.OPTION_REGISTRY", options, create=True))
    return stack


def _mk_fragment(
    name: str, reads_options: tuple[str, ...] = (), enables_default: bool = True
) -> Fragment:
    return Fragment(
        name=name,
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(
                fragment_dir=f"{name}/python", reads_options=reads_options
            )
        },
    )


def _mk_option(path: str, enables: dict[object, tuple[str, ...]]) -> Option:
    return Option(
        path=path,
        type=OptionType.BOOL,
        category=FeatureCategory.RELIABILITY,
        default=True,
        summary=f"option {path}",
        description=f"option {path}",
        enables=enables,
    )


class TestReadsOptionsValidation:
    def test_valid_reads_options_accepted(self) -> None:
        fragments = {
            "corr": _mk_fragment("corr", reads_options=("corr.always_on",))
        }
        options = {
            "corr.always_on": _mk_option("corr.always_on", enables={True: ("corr",)})
        }
        with _isolated_registries(fragments, options):
            plan = resolve(ProjectConfig(project_name="p", backends=[_mk_backend()]))
        assert [rf.fragment.name for rf in plan.ordered] == ["corr"]

    def test_orphan_reads_options_path_raises(self) -> None:
        fragments = {
            "bad": _mk_fragment("bad", reads_options=("nonexistent.path",))
        }
        options = {
            "bad.toggle": _mk_option("bad.toggle", enables={True: ("bad",)})
        }
        with _isolated_registries(fragments, options), pytest.raises(OptionsError) as excinfo:
            resolve(ProjectConfig(project_name="p", backends=[_mk_backend()]))
        assert "nonexistent.path" in excinfo.value.message
        assert excinfo.value.context["fragment"] == "bad"
        assert excinfo.value.context["path"] == "nonexistent.path"


# ---------------------------------------------------------------------------
# inject.yaml render: true flag
# ---------------------------------------------------------------------------


class TestRenderSnippet:
    def test_plain_snippet_unchanged(self) -> None:
        assert _render_snippet("pass", {}) == "pass"

    def test_substitutes_option_value(self) -> None:
        rendered = _render_snippet("TOP_K = {{ top_k }}", {"top_k": 10})
        assert rendered == "TOP_K = 10"

    def test_undefined_variable_raises(self) -> None:
        with pytest.raises(FragmentError) as excinfo:
            _render_snippet("TOP_K = {{ missing }}", {"top_k": 10})
        assert "undefined variable" in excinfo.value.message

    def test_nested_access_via_options_dict(self) -> None:
        # Declared paths pass through verbatim. Dotted paths aren't
        # valid Python identifiers so callers that want them must reach
        # in via the `options` mapping Jinja also exposes.
        rendered = _render_snippet('PATH = "{{ options["rag.top_k"] }}"', {"rag.top_k": 5})
        assert rendered == 'PATH = "5"'


class TestLoadInjectionsWithRender:
    def test_render_false_uses_snippet_verbatim(self, tmp_path: Path) -> None:
        inject_path = tmp_path / "inject.yaml"
        inject_path.write_text(
            "- target: main.py\n"
            "  marker: FORGE:MIDDLEWARE\n"
            "  snippet: 'TOP_K = {{ top_k }}'\n",
            encoding="utf-8",
        )
        injs = _load_injections(inject_path, "f", options={"top_k": 5})
        # No render: true, so no substitution — Jinja markers survive.
        assert injs[0].snippet == "TOP_K = {{ top_k }}"

    def test_render_true_substitutes(self, tmp_path: Path) -> None:
        inject_path = tmp_path / "inject.yaml"
        inject_path.write_text(
            "- target: main.py\n"
            "  marker: FORGE:MIDDLEWARE\n"
            "  render: true\n"
            "  snippet: 'TOP_K = {{ top_k }}'\n",
            encoding="utf-8",
        )
        injs = _load_injections(inject_path, "f", options={"top_k": 5})
        assert injs[0].snippet == "TOP_K = 5"

    def test_render_true_with_no_options_raises(self, tmp_path: Path) -> None:
        inject_path = tmp_path / "inject.yaml"
        inject_path.write_text(
            "- target: main.py\n"
            "  marker: FORGE:M\n"
            "  render: true\n"
            "  snippet: 'VALUE = {{ top_k }}'\n",
            encoding="utf-8",
        )
        with pytest.raises(FragmentError):
            _load_injections(inject_path, "f", options={})


# ---------------------------------------------------------------------------
# apply_features threading (smoke test via a real fragment)
# ---------------------------------------------------------------------------


class TestApplyFeaturesThreadsOptions:
    def test_fragment_with_reads_options_sees_filtered_view(self, tmp_path: Path) -> None:
        """Build a one-fragment project; verify the _apply_fragment context
        has the declared option in ``ctx.options``.

        Uses monkeypatching of ``_apply_fragment`` to capture the context
        rather than the real filesystem dispatcher — the interesting
        behaviour is the ``FragmentContext`` shape, not the copy/inject
        I/O which is well-covered elsewhere.
        """
        import forge.feature_injector as fi

        captured: list[FragmentContext] = []

        def _capture(
            ctx: FragmentContext,
            impl: FragmentImplSpec,
            feature_key: str,
            **kwargs: object,  # Epic K added middlewares=; absorb any future kwargs too
        ) -> None:
            captured.append(ctx)

        fragments = {
            "corr": _mk_fragment("corr", reads_options=("corr.tenant_header",))
        }
        options = {
            "corr.tenant_header": Option(
                path="corr.tenant_header",
                type=OptionType.STR,
                category=FeatureCategory.RELIABILITY,
                default="x-tenant-id",
                summary="header",
                description="header",
                enables={},
            ),
            "corr.always_on": _mk_option("corr.always_on", enables={True: ("corr",)}),
        }
        backend_dir = tmp_path / "services" / "api"
        backend_dir.mkdir(parents=True)

        with _isolated_registries(fragments, options), patch.object(fi, "_apply_fragment", _capture):
            plan = resolve(ProjectConfig(project_name="p", backends=[_mk_backend()]))
            fi.apply_features(
                _mk_backend(),
                backend_dir,
                plan.ordered,
                quiet=True,
                option_values=plan.option_values,
                project_root=tmp_path,
            )

        assert len(captured) == 1
        ctx = captured[0]
        assert ctx.options == {"corr.tenant_header": "x-tenant-id"}
        assert ctx.project_root == tmp_path
        assert ctx.backend_dir == backend_dir
