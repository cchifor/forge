"""Unit tests for the UI app-shell layout-variant registry + config wiring.

Covers Phase 0b/1 of the frontend-layouts work: the ``LayoutVariant``
registry (`forge.layout_variants`) and ``FrontendConfig.layout`` validation.
"""

from __future__ import annotations

import pytest

from forge import layout_variants as lv
from forge.config import FrontendConfig, FrontendFramework


@pytest.fixture(autouse=True)
def _isolate_registry():
    """Restore built-in variants after any test that mutates the registry."""
    yield
    lv._reset_for_tests()


# --- registry ---------------------------------------------------------------


def test_builtin_sidebar_registered_for_every_framework():
    for fw in (FrontendFramework.VUE, FrontendFramework.SVELTE, FrontendFramework.FLUTTER):
        variant = lv.get_layout_variant(fw, "sidebar")
        assert variant is not None, f"sidebar missing for {fw.value}"
        assert variant.template_dir.startswith("apps/")
        assert variant.base_template_dir == ""  # self-contained single render in v1


def test_default_layout_constant_is_sidebar():
    assert lv.DEFAULT_LAYOUT == "sidebar"
    assert FrontendConfig(framework=FrontendFramework.VUE, project_name="t").layout == "sidebar"


def test_available_layouts_per_framework():
    # Vue ships the full set in v1; Svelte/Flutter ship sidebar only (Phase 5
    # adds the rest). Discovered from templates/layouts/<fw>/<name>/layout.toml.
    assert lv.available_layouts(FrontendFramework.VUE) == (
        "bento",
        "docs",
        "sidebar",
        "tabbar",
        "threepane",
        "topnav",
    )
    assert lv.available_layouts(FrontendFramework.SVELTE) == ("sidebar",)
    assert lv.available_layouts(FrontendFramework.FLUTTER) == ("sidebar",)


def test_get_unknown_layout_returns_none():
    assert lv.get_layout_variant(FrontendFramework.VUE, "nope") is None


def test_register_and_lookup_roundtrip():
    lv.register_layout_variant(
        lv.LayoutVariant(FrontendFramework.VUE, "demolayout1", "apps/vue-frontend-template-demolayout1", "Top-Nav")
    )
    got = lv.get_layout_variant(FrontendFramework.VUE, "demolayout1")
    assert got is not None and got.display_label == "Top-Nav"
    assert "demolayout1" in lv.available_layouts(FrontendFramework.VUE)


def test_duplicate_registration_raises():
    with pytest.raises(ValueError, match="already registered"):
        lv.register_layout_variant(
            lv.LayoutVariant(FrontendFramework.VUE, "sidebar", "apps/vue-frontend-template", "dup")
        )


def test_unsupported_variant_hidden_from_available_but_resolvable():
    lv.register_layout_variant(
        lv.LayoutVariant(
            FrontendFramework.SVELTE, "demolayout2", "apps/svelte-frontend-template-demolayout2", "Bento", supported=False
        )
    )
    assert "demolayout2" not in lv.available_layouts(FrontendFramework.SVELTE)
    assert lv.get_layout_variant(FrontendFramework.SVELTE, "demolayout2") is not None


# --- FrontendConfig.validate() ---------------------------------------------


def test_validate_accepts_registered_layout():
    FrontendConfig(framework=FrontendFramework.VUE, project_name="t", layout="sidebar").validate()


def test_validate_rejects_unregistered_layout():
    cfg = FrontendConfig(framework=FrontendFramework.VUE, project_name="t", layout="ghost")
    with pytest.raises(ValueError, match="[Ll]ayout 'ghost' is not available"):
        cfg.validate()


def test_validate_layout_is_framework_scoped():
    # A layout registered only for Vue must not validate for Svelte.
    lv.register_layout_variant(
        lv.LayoutVariant(FrontendFramework.VUE, "demolayout2", "apps/vue-frontend-template-demolayout2", "Bento")
    )
    FrontendConfig(framework=FrontendFramework.VUE, project_name="t", layout="demolayout2").validate()
    with pytest.raises(ValueError, match="not available for svelte"):
        FrontendConfig(framework=FrontendFramework.SVELTE, project_name="t", layout="demolayout2").validate()


# --- plugin API surface -----------------------------------------------------


def test_api_add_frontend_layout_registers_variant():
    from forge.api import ForgeAPI, PluginRegistration

    api = ForgeAPI(PluginRegistration(name="layout_plugin", module="m"))
    api.add_frontend_layout(
        FrontendFramework.VUE,
        "demolayout1",
        "apps/vue-frontend-template-demolayout1",
        "Top-Nav",
        base_template_dir="apps/vue-frontend-template",
    )
    variant = lv.get_layout_variant(FrontendFramework.VUE, "demolayout1")
    assert variant is not None
    assert variant.display_label == "Top-Nav"
    assert variant.base_template_dir == "apps/vue-frontend-template"
    assert "demolayout1" in lv.available_layouts(FrontendFramework.VUE)


def test_api_add_frontend_layout_accepts_string_framework():
    from forge.api import ForgeAPI, PluginRegistration

    api = ForgeAPI(PluginRegistration(name="layout_plugin", module="m"))
    api.add_frontend_layout("vue", "demolayout2", "apps/vue-frontend-template-demolayout2", "Bento")
    assert lv.get_layout_variant(FrontendFramework.VUE, "demolayout2") is not None


def test_none_framework_skips_layout_validation():
    # NONE returns early (before the layout check); an arbitrary layout value
    # must not raise. include_auth=False avoids the pre-existing NONE
    # feature-flag guard so we isolate the layout-skip behavior.
    FrontendConfig(
        framework=FrontendFramework.NONE,
        project_name="t",
        layout="whatever",
        include_auth=False,
    ).validate()
