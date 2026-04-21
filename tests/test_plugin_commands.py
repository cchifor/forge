"""Tests for plugin-registered CLI commands (A4-2)."""

from __future__ import annotations

import argparse
from unittest.mock import patch

import pytest

from forge import plugins
from forge.api import ForgeAPI, PluginRegistration
from forge.cli.parser import _build_parser
from forge.errors import PluginError


@pytest.fixture(autouse=True)
def _reset_plugins():
    plugins.reset_for_tests()
    yield
    plugins.reset_for_tests()


class TestAddCommand:
    def test_registers_into_command_registry(self) -> None:
        reg = PluginRegistration(name="p", module="m")
        api = ForgeAPI(reg)
        handler = lambda args: 0  # noqa: E731
        api.add_command("mycompany-audit", handler)
        assert "mycompany-audit" in plugins.COMMAND_REGISTRY
        assert plugins.COMMAND_REGISTRY["mycompany-audit"] is handler
        assert reg.commands_added == 1

    def test_rejects_collision(self) -> None:
        reg = PluginRegistration(name="p", module="m")
        api = ForgeAPI(reg)
        api.add_command("mycmd", lambda args: 0)
        api2 = ForgeAPI(PluginRegistration(name="p2", module="m2"))
        with pytest.raises(PluginError, match="already claimed"):
            api2.add_command("mycmd", lambda args: 0)


class TestParserInjection:
    def test_plugin_command_shows_up_as_flag(self) -> None:
        reg = PluginRegistration(name="p", module="m")
        api = ForgeAPI(reg)
        api.add_command("audit-log", lambda args: 0)
        parser = _build_parser()
        flags = {o for a in parser._actions for o in a.option_strings}
        assert "--audit-log" in flags

    def test_plugin_flag_has_proper_dest(self) -> None:
        reg = PluginRegistration(name="p", module="m")
        api = ForgeAPI(reg)
        api.add_command("mycompany-audit", lambda args: 0)
        parser = _build_parser()
        args = parser.parse_args(["--mycompany-audit"])
        assert args.plugin_cmd_mycompany_audit is True

    def test_existing_flag_is_not_shadowed(self) -> None:
        """Plugins can't accidentally shadow a core flag (e.g. --json)."""
        reg = PluginRegistration(name="p", module="m")
        api = ForgeAPI(reg)
        # This is a bad-plugin pattern, but the parser should just skip
        # registration rather than crash.
        api.add_command("json", lambda args: 0)
        parser = _build_parser()
        # --json is still bound to json_output, not to the plugin command.
        args = parser.parse_args(["--json"])
        assert args.json_output is True


class TestDispatcher:
    def test_handler_invoked_and_exit_code_respected(self) -> None:
        called_with = []

        def handler(args: argparse.Namespace) -> int:
            called_with.append(args)
            return 3

        reg = PluginRegistration(name="p", module="m")
        api = ForgeAPI(reg)
        api.add_command("my-cmd", handler)
        parser = _build_parser()
        args = parser.parse_args(["--my-cmd"])

        # Simulate main()'s dispatch loop.
        from forge.plugins import COMMAND_REGISTRY

        for name, h in COMMAND_REGISTRY.items():
            dest = f"plugin_cmd_{name.replace('-', '_')}"
            if getattr(args, dest, False):
                code = h(args)
                assert code == 3
                assert called_with[0] is args
                return
        pytest.fail("handler was not invoked")
