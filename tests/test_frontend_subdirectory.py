"""Tests for ``frontend_uses_subdirectory`` (Epic S follow-on).

The helper replaces a string-equality branch in ``generator._generate_frontend``
that only knew about the built-in Flutter case; these tests lock in the
behavior for built-ins and for plugin frameworks that register their own
``FrontendSpec.uses_subdirectory`` flag.
"""

from __future__ import annotations

import pytest

from forge.config import (
    FRONTEND_SPECS,
    PLUGIN_FRAMEWORKS,
    FrontendFramework,
    FrontendSpec,
    frontend_uses_subdirectory,
    register_frontend_framework,
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


class TestBuiltins:
    def test_vue_uses_subdirectory(self) -> None:
        assert frontend_uses_subdirectory(FrontendFramework.VUE) is True

    def test_svelte_uses_subdirectory(self) -> None:
        assert frontend_uses_subdirectory(FrontendFramework.SVELTE) is True

    def test_flutter_does_not(self) -> None:
        assert frontend_uses_subdirectory(FrontendFramework.FLUTTER) is False

    def test_none_uses_subdirectory(self) -> None:
        # ``NONE`` never reaches ``_generate_frontend``, but the helper
        # shouldn't raise if it's called — defaulting to True is the
        # Copier convention.
        assert frontend_uses_subdirectory(FrontendFramework.NONE) is True


class TestPluginFrameworks:
    def test_plugin_default_true_when_unregistered(self) -> None:
        sentinel = register_frontend_framework("unregistered_plugin_fw")
        # Intentionally do NOT insert into FRONTEND_SPECS — helper should
        # default to True rather than KeyError, so the generator's only
        # failure mode remains Copier itself complaining about the
        # missing template.
        assert frontend_uses_subdirectory(sentinel) is True

    def test_plugin_reads_spec_flag_true(self) -> None:
        sentinel = register_frontend_framework("solid_fake")
        FRONTEND_SPECS["solid_fake"] = FrontendSpec(
            template_dir="apps/solid-fake",
            display_label="Solid (fake)",
            uses_subdirectory=True,
        )
        assert frontend_uses_subdirectory(sentinel) is True

    def test_plugin_reads_spec_flag_false(self) -> None:
        sentinel = register_frontend_framework("flutter_like")
        FRONTEND_SPECS["flutter_like"] = FrontendSpec(
            template_dir="apps/flutter-like",
            display_label="Flutter-like plugin",
            uses_subdirectory=False,
        )
        assert frontend_uses_subdirectory(sentinel) is False


class TestFrontendSpecDefault:
    def test_default_is_true(self) -> None:
        spec = FrontendSpec(template_dir="x", display_label="y")
        assert spec.uses_subdirectory is True
