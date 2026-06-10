"""Tests for headless mode config building."""

import json
import subprocess
import sys
from argparse import Namespace
from pathlib import Path

import pytest

from forge.cli import _build_config, _is_headless, _load_config_file
from forge.config import FrontendFramework


def _default_args(**overrides):
    """Create an args namespace with all defaults set to None."""
    defaults = dict(
        config=None,
        project_name=None,
        description=None,
        output_dir=".",
        backend_port=None,
        python_version=None,
        frontend=None,
        features=None,
        author_name=None,
        package_manager=None,
        frontend_port=None,
        color_scheme=None,
        org_name=None,
        include_auth=None,
        include_chat=None,
        include_openapi=None,
        keycloak_port=None,
        keycloak_realm=None,
        keycloak_client_id=None,
        yes=False,
        no_docker=False,
        quiet=False,
        json_output=False,
    )
    defaults.update(overrides)
    return Namespace(**defaults)


class TestIsHeadless:
    def test_no_args_is_interactive(self):
        assert not _is_headless(_default_args())

    def test_config_flag_is_headless(self):
        assert _is_headless(_default_args(config="stack.yaml"))

    def test_project_name_flag_is_headless(self):
        assert _is_headless(_default_args(project_name="test"))

    def test_yes_flag_is_headless(self):
        assert _is_headless(_default_args(yes=True))

    def test_frontend_flag_is_headless(self):
        assert _is_headless(_default_args(frontend="vue"))


class TestEveryFlagTriggersHeadless:
    """Regression guard for the silently-discarded-flags bug: _is_headless
    used to be a hand-maintained 13-flag list, so `forge --platform X`
    (and ~15 other flags) dropped the flag and opened the wizard. The
    generic baseline comparison must detect EVERY current and future
    generation flag; report-only flags are denylisted explicitly."""

    @staticmethod
    def _sample_argv(action) -> list[str] | None:
        flag = action.option_strings[-1]
        if action.nargs == 0:
            return [flag]
        if action.choices:
            for choice in action.choices:
                if choice != action.default:
                    return [flag, str(choice)]
            return None  # degenerate: single choice equal to the default
        if action.type is int or isinstance(action.default, int):
            return [flag, str((action.default or 0) + 1)]
        if isinstance(action.default, str):
            return [flag, action.default + "x"]
        return [flag, "sample"]

    def test_every_option_flag_triggers_headless(self):
        from forge.cli.parser import _MODE_ONLY_DESTS, _build_parser

        parser = _build_parser()
        missed: list[str] = []
        for action in parser._actions:
            if not action.option_strings or action.dest == "help":
                continue
            if action.dest in _MODE_ONLY_DESTS:
                continue
            argv = self._sample_argv(action)
            if argv is None:
                continue
            ns = parser.parse_args(argv)
            if not _is_headless(ns):
                missed.append(" ".join(argv))
        assert not missed, (
            "flags parsed but NOT detected by _is_headless (they would be "
            f"silently discarded in interactive mode): {missed}"
        )

    def test_mode_only_flags_stay_interactive(self):
        from forge.cli.parser import _build_parser

        parser = _build_parser()
        for argv in (["--verbose"], ["--log-json"], ["--log-level", "DEBUG"]):
            assert not _is_headless(parser.parse_args(argv)), argv

    def test_platform_flag_is_headless(self):
        # The motivating bug: `forge --platform <preset>` must run headless
        # with the preset applied, not silently fall into the wizard.
        from forge.cli.parser import _build_parser

        ns = _build_parser().parse_args(["--platform", "monolithic"])
        assert _is_headless(ns)


class TestBuildConfig:
    def test_defaults_only(self):
        config = _build_config(_default_args(), {})
        assert config.project_name == "My Platform"
        assert config.backend.server_port == 5000
        assert config.frontend is None

    def test_from_config_dict(self):
        cfg = {
            "project_name": "my-shop",
            "backend": {"features": "products, orders"},
            "frontend": {"framework": "vue"},
        }
        config = _build_config(_default_args(), cfg)
        assert config.project_name == "my-shop"
        assert config.frontend.framework == FrontendFramework.VUE
        assert config.backend.features == ["products", "orders"]
        assert config.all_features == ["products", "orders"]

    def test_components_list_from_config(self):
        config = _build_config(_default_args(), {"components": ["StatCard", "Panel"]})
        assert config.components == ["StatCard", "Panel"]

    def test_components_absent_defaults_empty(self):
        assert _build_config(_default_args(), {}).components == []

    def test_malformed_components_raises(self):
        import pytest

        with pytest.raises(ValueError, match="list of component-name strings"):
            _build_config(_default_args(), {"components": "StatCard"})
        with pytest.raises(ValueError, match="list of component-name strings"):
            _build_config(_default_args(), {"components": [123]})

    def test_cli_flags_override_config(self):
        cfg = {"project_name": "from-file"}
        args = _default_args(project_name="from-flag")
        config = _build_config(args, cfg)
        assert config.project_name == "from-flag"

    def test_backend_port_from_flag(self):
        args = _default_args(backend_port=8000)
        config = _build_config(args, {})
        assert config.backend.server_port == 8000

    def test_frontend_none(self):
        args = _default_args(frontend="none")
        config = _build_config(args, {})
        assert config.frontend is None

    def test_keycloak_from_config(self):
        cfg = {
            "frontend": {"framework": "vue", "include_auth": True},
            "keycloak": {"port": 9090, "realm": "dev", "client_id": "myapp"},
        }
        config = _build_config(_default_args(), cfg)
        assert config.include_keycloak is True
        assert config.keycloak_port == 9090
        assert config.frontend.keycloak_realm == "dev"

    def test_no_auth_disables_keycloak(self):
        cfg = {"frontend": {"framework": "svelte", "include_auth": False}}
        config = _build_config(_default_args(), cfg)
        assert config.include_keycloak is False

    def test_features_flag_sets_backend_features(self):
        """--features CLI flag should set backend features, not frontend."""
        args = _default_args(features="products, orders", frontend="vue")
        config = _build_config(args, {})
        assert config.backend.features == ["products", "orders"]
        assert config.all_features == ["products", "orders"]

    def test_backend_features_from_config_file(self):
        """Single backend features from config file flow to all_features."""
        cfg = {
            "backend": {"features": "widgets, gadgets"},
            "frontend": {"framework": "svelte"},
        }
        config = _build_config(_default_args(), cfg)
        assert config.backend.features == ["widgets", "gadgets"]
        assert config.all_features == ["widgets", "gadgets"]

    def test_multi_backend_features_aggregate(self):
        """Multi-backend features aggregate into all_features."""
        cfg = {
            "backends": [
                {"name": "svc-a", "language": "python", "features": ["items", "orders"]},
                {
                    "name": "svc-b",
                    "language": "node",
                    "features": ["products"],
                    "server_port": 5001,
                },
            ],
            "frontend": {"framework": "vue"},
        }
        config = _build_config(_default_args(), cfg)
        assert config.all_features == ["items", "orders", "products"]

    def test_default_backend_features_when_none_specified(self):
        """Backend defaults to ['items'] when no features specified."""
        config = _build_config(_default_args(), {})
        assert config.backend.features == ["items"]


class TestLoadConfigFile:
    def test_json_file(self, tmp_path):
        f = tmp_path / "config.json"
        f.write_text(json.dumps({"project_name": "test"}))
        result = _load_config_file(str(f))
        assert result["project_name"] == "test"

    def test_yaml_file(self, tmp_path):
        f = tmp_path / "config.yaml"
        f.write_text("project_name: test\n")
        result = _load_config_file(str(f))
        assert result["project_name"] == "test"

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(ValueError, match="Config file not found"):
            _load_config_file(str(tmp_path / "nope.json"))


class TestNonTtyRefusesToPrompt:
    """Regression: headless mode without ``--yes`` must not hang or exit
    silently when stdin isn't a TTY. An interactive ``questionary`` prompt
    in that situation kills the process with exit 1 and no structured
    output, which leaves agents (Claude Code / Codex / CI) unable to
    classify the failure.
    """

    @staticmethod
    def _forge_bin() -> Path:
        # ``console_scripts`` install the entry point next to the
        # interpreter; works whether we're inside ``.venv`` or not.
        return Path(sys.executable).parent / "forge"

    def test_json_non_tty_emits_error_envelope(self, tmp_path):
        forge_bin = self._forge_bin()
        if not forge_bin.is_file():
            pytest.skip(f"forge entry point not installed at {forge_bin}")

        cfg = tmp_path / "forge.yaml"
        cfg.write_text(
            "project_name: hf3-smoke\n"
            "backend:\n"
            "  language: python\n"
            "  features: [items]\n"
            "frontend:\n"
            "  framework: none\n"
        )

        proc = subprocess.run(
            [
                str(forge_bin),
                "--config",
                str(cfg),
                "--json",
                "--no-docker",
                "--output-dir",
                str(tmp_path / "out"),
            ],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=30,
        )

        assert proc.returncode == 2, (
            f"expected exit 2, got {proc.returncode}\n"
            f"stdout: {proc.stdout!r}\nstderr: {proc.stderr!r}"
        )
        payload = json.loads(proc.stdout.strip().splitlines()[-1])
        assert "error" in payload
        assert "yes" in payload["error"].lower() or "stdin" in payload["error"].lower()
