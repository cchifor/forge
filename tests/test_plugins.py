"""Tests for the plugin API and entry-point discovery (0.3 of 1.0 roadmap)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from forge import plugins
from forge.api import ForgeAPI, PluginRegistration
from forge.errors import PluginError
from forge.options import OPTION_ALIAS_INDEX, OPTION_REGISTRY


@pytest.fixture(autouse=True)
def _reset_plugins():
    plugins.reset_for_tests()
    yield
    plugins.reset_for_tests()


@pytest.fixture
def _isolate_option_registry():
    """Snapshot + restore OPTION_REGISTRY and OPTION_ALIAS_INDEX around a test.

    Several add_option tests below mutate the live registry (and its
    alias index sidecar). Without isolation, a test that registers
    ``testplugin.flag`` leaks into the next test and the registry
    invariant tests in test_options.py would see plugin entries.
    """
    saved_registry = dict(OPTION_REGISTRY)
    saved_aliases = dict(OPTION_ALIAS_INDEX)
    try:
        yield
    finally:
        OPTION_REGISTRY.clear()
        OPTION_REGISTRY.update(saved_registry)
        OPTION_ALIAS_INDEX.clear()
        OPTION_ALIAS_INDEX.update(saved_aliases)


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
        # Extractor scaffolding (Phase 3): empty by default.
        assert data["extractors_added"] == []


class TestForgeAPI:
    def test_add_option_registers_and_counts(self, _isolate_option_registry) -> None:
        from forge.options import FeatureCategory, Option, OptionType

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
        with pytest.raises(PluginError, match="already registered"):
            api.add_option(opt)
        assert reg.options_added == 0

    def test_add_option_updates_alias_index(self, _isolate_option_registry) -> None:
        """Initiative #2 sub-task 1: add_option must go through
        register_option so the OPTION_ALIAS_INDEX picks up plugin
        aliases the same way it picks up built-in ones."""
        from forge.options import FeatureCategory, Option, OptionType, resolve_alias

        reg = PluginRegistration(name="p", module="m")
        api = ForgeAPI(reg)

        opt = Option(
            path="testplugin.canonical",
            type=OptionType.BOOL,
            category=FeatureCategory.OBSERVABILITY,
            default=False,
            summary="canonical-with-alias",
            description="exercises alias-index update via add_option",
            aliases=("testplugin.legacy", "testplugin.older"),
            deprecated_since="1.2.0",
        )
        api.add_option(opt)

        assert "testplugin.canonical" in OPTION_REGISTRY
        # Both aliases must resolve via the alias index — proving
        # add_option no longer writes directly to OPTION_REGISTRY but
        # delegates to register_option().
        assert resolve_alias("testplugin.legacy") == "testplugin.canonical"
        assert resolve_alias("testplugin.older") == "testplugin.canonical"
        assert reg.options_added == 1

    def test_add_option_rejects_alias_collision(self, _isolate_option_registry) -> None:
        """Two plugin options whose aliases collide must surface as a
        PluginError, not a raw ValueError from register_option."""
        from forge.options import FeatureCategory, Option, OptionType

        reg = PluginRegistration(name="p", module="m")
        api = ForgeAPI(reg)

        first = Option(
            path="testplugin.first",
            type=OptionType.BOOL,
            category=FeatureCategory.OBSERVABILITY,
            default=False,
            summary="first",
            description="first option",
            aliases=("testplugin.shared_alias",),
            deprecated_since="1.2.0",
        )
        api.add_option(first)

        second = Option(
            path="testplugin.second",
            type=OptionType.BOOL,
            category=FeatureCategory.OBSERVABILITY,
            default=False,
            summary="second",
            description="second option",
            aliases=("testplugin.shared_alias",),
            deprecated_since="1.2.0",
        )
        with pytest.raises(PluginError, match="already aliased"):
            api.add_option(second)
        # First registration intact; second's counter did NOT bump.
        assert reg.options_added == 1
        assert "testplugin.first" in OPTION_REGISTRY
        assert "testplugin.second" not in OPTION_REGISTRY

    def test_add_option_rejects_path_aliasing_existing_canonical(
        self, _isolate_option_registry
    ) -> None:
        """A plugin option whose path equals an existing alias must be
        rejected — the alias index would otherwise become inconsistent."""
        from forge.options import FeatureCategory, Option, OptionType

        reg = PluginRegistration(name="p", module="m")
        api = ForgeAPI(reg)

        first = Option(
            path="testplugin.canonical",
            type=OptionType.BOOL,
            category=FeatureCategory.OBSERVABILITY,
            default=False,
            summary="first",
            description="first option",
            aliases=("testplugin.shadow",),
            deprecated_since="1.2.0",
        )
        api.add_option(first)

        # Second tries to register the SAME path as the first's alias.
        clash = Option(
            path="testplugin.shadow",
            type=OptionType.BOOL,
            category=FeatureCategory.OBSERVABILITY,
            default=False,
            summary="clash",
            description="clash option",
        )
        with pytest.raises(PluginError, match="path collides with an existing alias"):
            api.add_option(clash)
        assert reg.options_added == 1

    def test_add_option_retains_option_registration(
        self, _isolate_option_registry
    ) -> None:
        """Initiative #2 sub-task 1: the Option object must be retained
        on PluginRegistration.option_registrations so downstream
        consumers can introspect plugin-registered options without
        re-reading OPTION_REGISTRY."""
        from forge.api import PluginOptionRegistration
        from forge.options import FeatureCategory, Option, OptionType

        reg = PluginRegistration(name="my_plugin", module="m")
        api = ForgeAPI(reg)

        opt = Option(
            path="testplugin.retained",
            type=OptionType.BOOL,
            category=FeatureCategory.OBSERVABILITY,
            default=False,
            summary="retained",
            description="retained option",
        )
        api.add_option(opt)

        assert len(reg.option_registrations) == 1
        registration = reg.option_registrations[0]
        assert isinstance(registration, PluginOptionRegistration)
        assert registration.option is opt
        assert registration.plugin_name == "my_plugin"

    def test_add_option_accumulates_registrations(
        self, _isolate_option_registry
    ) -> None:
        """Multiple add_option calls accumulate into the tuple in order."""
        from forge.options import FeatureCategory, Option, OptionType

        reg = PluginRegistration(name="p", module="m")
        api = ForgeAPI(reg)

        first = Option(
            path="testplugin.first",
            type=OptionType.BOOL,
            category=FeatureCategory.OBSERVABILITY,
            default=False,
            summary="first",
            description="first option",
        )
        second = Option(
            path="testplugin.second",
            type=OptionType.BOOL,
            category=FeatureCategory.OBSERVABILITY,
            default=True,
            summary="second",
            description="second option",
        )
        api.add_option(first)
        api.add_option(second)

        assert reg.options_added == 2
        assert len(reg.option_registrations) == 2
        assert [r.option.path for r in reg.option_registrations] == [
            "testplugin.first",
            "testplugin.second",
        ]

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

    def test_add_emitter_retains_emitter_registration(self) -> None:
        """Initiative #2 sub-task 2: the emitter callable must be
        retained on PluginRegistration.emitter_registrations so the
        codegen pipeline can walk LOADED_PLUGINS and invoke each
        plugin's emitter after the built-in passes."""
        from forge.api import PluginEmitterRegistration

        reg = PluginRegistration(name="my_plugin", module="m")
        api = ForgeAPI(reg)

        def fn(project_root, config, resolved):  # noqa: ARG001
            return None

        api.add_emitter("openapi", fn)

        assert len(reg.emitter_registrations) == 1
        registration = reg.emitter_registrations[0]
        assert isinstance(registration, PluginEmitterRegistration)
        assert registration.target == "openapi"
        assert registration.emitter is fn
        assert registration.plugin_name == "my_plugin"

    def test_add_emitter_accumulates_across_targets(self) -> None:
        """Multiple add_emitter calls accumulate into the tuple."""
        reg = PluginRegistration(name="p", module="m")
        api = ForgeAPI(reg)

        def emit_py(project_root, config, resolved):  # noqa: ARG001
            return None

        def emit_ts(project_root, config, resolved):  # noqa: ARG001
            return None

        api.add_emitter("python", emit_py)
        api.add_emitter("typescript", emit_ts)

        assert reg.emitters_added == 2
        assert len(reg.emitter_registrations) == 2
        targets = [r.target for r in reg.emitter_registrations]
        assert targets == ["python", "typescript"]
        # Back-compat: ``_emitters`` dict still populated.
        assert api._emitters == {"python": emit_py, "typescript": emit_ts}

    def test_add_emitter_same_target_last_wins_on_dict(self) -> None:
        """When the same plugin re-registers a target, the dict
        last-wins (back-compat with the 1.0.0a1 shape). Both
        registrations are retained on the tuple so the codegen
        walker can spot the collision and warn."""
        reg = PluginRegistration(name="p", module="m")
        api = ForgeAPI(reg)

        def first(project_root, config, resolved):  # noqa: ARG001
            return None

        def second(project_root, config, resolved):  # noqa: ARG001
            return None

        api.add_emitter("python", first)
        api.add_emitter("python", second)

        assert reg.emitters_added == 2
        assert api._emitters["python"] is second
        # Both registrations retained on the tuple — pipeline walker
        # is responsible for last-wins resolution + warning.
        assert len(reg.emitter_registrations) == 2
        assert [r.emitter for r in reg.emitter_registrations] == [first, second]

    def test_add_extractor_records_registration(self) -> None:
        reg = PluginRegistration(name="p", module="m")
        api = ForgeAPI(reg)

        class _StubExtractor:
            kind = "files"

            def extract(self, ctx, plan):  # noqa: ARG002
                return []

        api.add_extractor("files", _StubExtractor())
        assert reg.extractors_added == (("files", None),)

    def test_add_extractor_supports_fragment_scope(self) -> None:
        reg = PluginRegistration(name="p", module="m")
        api = ForgeAPI(reg)

        class _StubExtractor:
            kind = "block"

            def extract(self, ctx, plan):  # noqa: ARG002
                return []

        api.add_extractor("block", _StubExtractor(), fragment="auth_jwt")
        assert reg.extractors_added == (("block", "auth_jwt"),)

    def test_add_extractor_accumulates_across_calls(self) -> None:
        reg = PluginRegistration(name="p", module="m")
        api = ForgeAPI(reg)

        class _StubExtractor:
            kind = "deps"

            def extract(self, ctx, plan):  # noqa: ARG002
                return []

        api.add_extractor("deps", _StubExtractor())
        api.add_extractor("env", _StubExtractor(), fragment="rag_pgvector")
        assert reg.extractors_added == (
            ("deps", None),
            ("env", "rag_pgvector"),
        )

    def test_add_extractor_rejects_unknown_kind(self) -> None:
        reg = PluginRegistration(name="p", module="m")
        api = ForgeAPI(reg)
        with pytest.raises(PluginError, match="unknown kind"):
            api.add_extractor("bogus", object())
        assert reg.extractors_added == ()

    def test_add_extractor_retains_extractor_callable(self) -> None:
        # Initiative #1 sub-task 4: the extractor instance must be
        # retained on PluginRegistration.extractor_registrations so the
        # harvester can actually invoke it. Pre-sub-task-4 the API did
        # ``del extractor`` and only kept the (kind, fragment) tag.
        reg = PluginRegistration(name="p", module="m")
        api = ForgeAPI(reg)

        class _StubExtractor:
            kind = "files"

            def extract(self, ctx, plan):  # noqa: ARG002
                return []

        instance = _StubExtractor()
        api.add_extractor("files", instance)

        assert len(reg.extractor_registrations) == 1
        registration = reg.extractor_registrations[0]
        assert registration.kind == "files"
        assert registration.fragment is None
        assert registration.extractor is instance

    def test_add_extractor_preserves_fragment_scope(self) -> None:
        reg = PluginRegistration(name="p", module="m")
        api = ForgeAPI(reg)

        class _StubExtractor:
            kind = "block"

            def extract(self, ctx, plan):  # noqa: ARG002
                return []

        instance = _StubExtractor()
        api.add_extractor("block", instance, fragment="auth_jwt")

        assert len(reg.extractor_registrations) == 1
        registration = reg.extractor_registrations[0]
        assert registration.kind == "block"
        assert registration.fragment == "auth_jwt"
        assert registration.extractor is instance
        # The harvester pipeline assembler treats fragment-scoped
        # overrides as deferred (still recorded, not yet invoked).
        # Drift-gate the assertion as documentation of the contract.
        assert registration.as_legacy_pair == ("block", "auth_jwt")

    def test_as_dict_surfaces_extractor_registrations(self) -> None:
        reg = PluginRegistration(name="p", module="m")
        api = ForgeAPI(reg)

        class _StubExtractor:
            kind = "files"

            def extract(self, ctx, plan):  # noqa: ARG002
                return []

        api.add_extractor("files", _StubExtractor())
        api.add_extractor("block", _StubExtractor(), fragment="auth")
        payload = reg.as_dict()
        assert payload["extractors_added"] == [["files", None], ["block", "auth"]]

    def test_add_service_registers_template(self) -> None:
        from forge.services import ServiceTemplate
        from forge.services.registry import (
            SERVICE_REGISTRY,
            reset_for_tests as reset_services,
        )

        reset_services()
        reg = PluginRegistration(name="p", module="m")
        api = ForgeAPI(reg)
        tpl = ServiceTemplate(name="my_svc", image="my/svc:1")
        api.add_service("my_capability", tpl)
        assert SERVICE_REGISTRY["my_capability"] == tpl
        reset_services()

    def test_add_service_rejects_non_template(self) -> None:
        reg = PluginRegistration(name="p", module="m")
        api = ForgeAPI(reg)
        with pytest.raises(PluginError):
            api.add_service("cap", {"name": "nope"})  # type: ignore[arg-type]

    def test_add_service_wraps_conflict_in_plugin_error(self) -> None:
        from forge.services import ServiceTemplate
        from forge.services.registry import reset_for_tests as reset_services

        reset_services()
        reg = PluginRegistration(name="p", module="m")
        api = ForgeAPI(reg)
        api.add_service("dup_cap", ServiceTemplate(name="a", image="i:1"))
        with pytest.raises(PluginError):
            api.add_service("dup_cap", ServiceTemplate(name="a", image="i:2"))
        reset_services()

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
