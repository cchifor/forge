"""Tests for the plugin API and entry-point discovery (0.3 of 1.0 roadmap)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from forge import plugins
from forge.api import ForgeAPI, PluginRegistration


@pytest.fixture(autouse=True)
def _reset_plugins():
    plugins.reset_for_tests()
    yield
    plugins.reset_for_tests()


class TestPluginRegistration:
    def test_as_dict_has_all_counters(self) -> None:
        reg = PluginRegistration(name="p1", module="mod.p1", version="0.1.0")
        reg.options_added = 2
        reg.fragments_added = 1
        data = reg.as_dict()
        assert data["name"] == "p1"
        assert data["version"] == "0.1.0"
        assert data["options_added"] == 2
        assert data["fragments_added"] == 1
        assert data["commands_added"] == 0


class TestForgeAPI:
    def test_add_option_registers_and_counts(self) -> None:
        from forge.options import OPTION_REGISTRY, FeatureCategory, Option, OptionType

        reg = PluginRegistration(name="p", module="m")
        api = ForgeAPI(reg)

        opt = Option(
            path="testplugin.flag",
            type=OptionType.BOOL,
            category=FeatureCategory.OBSERVABILITY,
            default=False,
            summary="test",
            description="test option",
        )
        api.add_option(opt)

        assert "testplugin.flag" in OPTION_REGISTRY
        assert reg.options_added == 1

        # Cleanup: remove the injected option so other tests aren't affected.
        OPTION_REGISTRY.pop("testplugin.flag", None)

    def test_add_option_rejects_collision(self) -> None:
        from forge.options import FeatureCategory, Option, OptionType

        reg = PluginRegistration(name="p", module="m")
        api = ForgeAPI(reg)

        opt = Option(
            path="middleware.rate_limit",  # existing built-in path
            type=OptionType.BOOL,
            category=FeatureCategory.RELIABILITY,
            default=False,
            summary="collision",
            description="collision",
        )
        with pytest.raises(ValueError, match="already registered"):
            api.add_option(opt)
        assert reg.options_added == 0

    def test_add_command_captures_handler(self) -> None:
        reg = PluginRegistration(name="p", module="m")
        api = ForgeAPI(reg)
        handler = lambda args: 0  # noqa: E731
        api.add_command("mycmd", handler)
        assert reg.commands_added == 1
        assert handler in api._commands

    def test_add_emitter_captures_callable(self) -> None:
        reg = PluginRegistration(name="p", module="m")
        api = ForgeAPI(reg)
        fn = lambda x: x  # noqa: E731
        api.add_emitter("dart", fn)
        assert reg.emitters_added == 1
        assert api._emitters["dart"] is fn

    def test_add_backend_accepts_plugin_language_in_a2(self) -> None:
        # 1.0.0a2: add_backend now supports plugin-defined languages.
        # See tests/test_plugin_backend_language.py for the full suite.
        from forge.config import BACKEND_REGISTRY, BackendSpec, resolve_backend_language

        reg = PluginRegistration(name="p", module="m")
        api = ForgeAPI(reg)
        spec = BackendSpec(
            template_dir="services/go-svc",
            display_label="Go",
            version_field="go_version",
            version_choices=("1.23",),
        )
        try:
            api.add_backend("go_plugin_test", spec)
            go = resolve_backend_language("go_plugin_test")
            assert BACKEND_REGISTRY[go] is spec
        finally:
            from forge.config import PLUGIN_LANGUAGES

            sentinel = PLUGIN_LANGUAGES.pop("go_plugin_test", None)
            if sentinel is not None:
                BACKEND_REGISTRY.pop(sentinel, None)


class TestLoadAll:
    def test_empty_when_no_plugins(self) -> None:
        with patch.object(plugins, "_iter_entry_points", return_value=()):
            result = plugins.load_all()
        assert result == []
        assert plugins.LOADED_PLUGINS == []
        assert plugins.FAILED_PLUGINS == []

    def test_records_successful_plugin(self) -> None:
        def fake_register(api: ForgeAPI) -> None:
            # No-op registration — we're testing the load machinery.
            pass

        ep = MagicMock()
        ep.name = "fake_plugin"
        ep.value = "fake_module:register"
        ep.dist = MagicMock(version="1.2.3")
        ep.load.return_value = fake_register

        with patch.object(plugins, "_iter_entry_points", return_value=[ep]):
            plugins.load_all()

        assert len(plugins.LOADED_PLUGINS) == 1
        assert plugins.LOADED_PLUGINS[0].name == "fake_plugin"
        assert plugins.LOADED_PLUGINS[0].version == "1.2.3"

    def test_captures_register_failure_without_blocking_others(self) -> None:
        def bad_register(api: ForgeAPI) -> None:
            raise RuntimeError("intentional")

        def good_register(api: ForgeAPI) -> None:
            pass

        bad_ep = MagicMock()
        bad_ep.name = "bad"
        bad_ep.load.return_value = bad_register
        good_ep = MagicMock()
        good_ep.name = "good"
        good_ep.load.return_value = good_register

        with patch.object(plugins, "_iter_entry_points", return_value=[bad_ep, good_ep]):
            plugins.load_all()

        assert any(n == "bad" for n, _ in plugins.FAILED_PLUGINS)
        assert any(reg.name == "good" for reg in plugins.LOADED_PLUGINS)

    def test_load_failure_captured(self) -> None:
        ep = MagicMock()
        ep.name = "broken"
        ep.load.side_effect = ImportError("no module")
        with patch.object(plugins, "_iter_entry_points", return_value=[ep]):
            plugins.load_all()
        assert ("broken", plugins.FAILED_PLUGINS[0][1]).__contains__
        assert "load failed" in plugins.FAILED_PLUGINS[0][1]

    def test_non_callable_target_rejected(self) -> None:
        ep = MagicMock()
        ep.name = "notfn"
        ep.load.return_value = "not a callable"
        with patch.object(plugins, "_iter_entry_points", return_value=[ep]):
            plugins.load_all()
        assert plugins.FAILED_PLUGINS[0][0] == "notfn"
        assert "not callable" in plugins.FAILED_PLUGINS[0][1]

    def test_idempotent(self) -> None:
        with patch.object(plugins, "_iter_entry_points", return_value=()):
            first = plugins.load_all()
            second = plugins.load_all()
        assert first is second  # same list, not reloaded


class TestDispatchPlugins:
    def test_list_empty_prints_guidance(self, capsys) -> None:
        from forge.cli.commands.plugins import _dispatch_plugins

        with patch.object(plugins, "_iter_entry_points", return_value=()):
            with pytest.raises(SystemExit) as exc:
                _dispatch_plugins("list")
        assert exc.value.code == 0
        out = capsys.readouterr().out
        assert "No forge plugins" in out

    def test_list_json_envelope(self, capsys) -> None:
        import json

        from forge.cli.commands.plugins import _dispatch_plugins

        with patch.object(plugins, "_iter_entry_points", return_value=()):
            with pytest.raises(SystemExit):
                _dispatch_plugins("list", json_output=True)
        payload = json.loads(capsys.readouterr().out.strip())
        assert payload == {"loaded": [], "failed": []}
