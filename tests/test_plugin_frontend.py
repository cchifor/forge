"""Tests for plugin-defined frontends (A4-4)."""

from __future__ import annotations

import pytest

from forge.api import ForgeAPI, PluginRegistration
from forge.config import (
    FRONTEND_SPECS,
    FrontendFramework,
    FrontendSpec,
    PLUGIN_FRAMEWORKS,
    register_frontend_framework,
    resolve_frontend_framework,
)


@pytest.fixture(autouse=True)
def _cleanup_plugin_frameworks():
    snapshot_pf = dict(PLUGIN_FRAMEWORKS)
    snapshot_specs = dict(FRONTEND_SPECS)
    yield
    for key in list(PLUGIN_FRAMEWORKS):
        if key not in snapshot_pf:
            PLUGIN_FRAMEWORKS.pop(key)
    for key in list(FRONTEND_SPECS):
        if key not in snapshot_specs:
            FRONTEND_SPECS.pop(key)


class TestResolveFrontendFramework:
    def test_builtin(self) -> None:
        assert resolve_frontend_framework("vue") is FrontendFramework.VUE
        assert resolve_frontend_framework("svelte") is FrontendFramework.SVELTE

    def test_plugin_after_register(self) -> None:
        register_frontend_framework("solid")
        resolved = resolve_frontend_framework("solid")
        assert resolved.value == "solid"

    def test_unknown_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown frontend framework"):
            resolve_frontend_framework("doesnotexist")


class TestAddFrontend:
    def test_plugin_registers_new_frontend(self) -> None:
        reg = PluginRegistration(name="solid_plugin", module="m")
        api = ForgeAPI(reg)
        spec = FrontendSpec(
            template_dir="apps/solid-frontend-template",
            display_label="SolidStart",
        )
        api.add_frontend("solid", spec)
        assert "solid" in FRONTEND_SPECS
        assert FRONTEND_SPECS["solid"] is spec
        assert resolve_frontend_framework("solid").value == "solid"

    def test_cannot_shadow_builtin(self) -> None:
        reg = PluginRegistration(name="p", module="m")
        api = ForgeAPI(reg)
        spec = FrontendSpec(template_dir="x", display_label="y")
        with pytest.raises(ValueError, match="built-in"):
            api.add_frontend("vue", spec)

    def test_cannot_shadow_another_plugin(self) -> None:
        reg = PluginRegistration(name="p1", module="m")
        api = ForgeAPI(reg)
        spec = FrontendSpec(template_dir="apps/remix", display_label="Remix")
        api.add_frontend("remix", spec)

        reg2 = PluginRegistration(name="p2", module="m")
        api2 = ForgeAPI(reg2)
        with pytest.raises(ValueError, match="already claimed"):
            api2.add_frontend("remix", spec)


class TestPluginFrameworkSentinel:
    def test_hash_consistency(self) -> None:
        a = register_frontend_framework("qwik")
        b = register_frontend_framework("qwik")
        d = {a: "value"}
        assert d[b] == "value"

    def test_equality_with_builtin(self) -> None:
        """A plugin sentinel never equals a built-in member, even with
        the same value (different source of truth, different spec)."""
        plugin_vue = register_frontend_framework("vue-plugin")
        assert plugin_vue != FrontendFramework.VUE
