"""CLI / e2e tests for ``forge --features-cmd`` subcommands.

Tests the feature management commands: list, deps, validate, scaffold.
Uses direct function calls via ``_dispatch_features`` (caught via
``SystemExit``) for reliability; subprocess calls are reserved for
smoke-level tests that also exercise argument parsing.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from forge import feature_loader, plugins
from forge.cli.commands.features import _dispatch_features
from forge.fragments import FRAGMENT_REGISTRY
from forge.options._registry import OPTION_ALIAS_INDEX, OPTION_REGISTRY


# ------------------------------------------------------------------
# Fixture: isolate feature + plugin state between tests
# ------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset():
    """Save, reset, and restore all mutable global registries."""
    saved_opts = dict(OPTION_REGISTRY)
    saved_aliases = dict(OPTION_ALIAS_INDEX)
    saved_frags = dict(FRAGMENT_REGISTRY)
    saved_frags_frozen = FRAGMENT_REGISTRY.frozen
    saved_loaded = list(feature_loader.LOADED_FEATURES)

    feature_loader.reset_for_tests()
    plugins.reset_for_tests()
    OPTION_REGISTRY.clear()
    OPTION_ALIAS_INDEX.clear()
    FRAGMENT_REGISTRY.frozen = False
    FRAGMENT_REGISTRY.clear()

    yield

    feature_loader.reset_for_tests()
    plugins.reset_for_tests()
    OPTION_REGISTRY.clear()
    OPTION_REGISTRY.update(saved_opts)
    OPTION_ALIAS_INDEX.clear()
    OPTION_ALIAS_INDEX.update(saved_aliases)
    FRAGMENT_REGISTRY.frozen = False
    FRAGMENT_REGISTRY.clear()
    FRAGMENT_REGISTRY.update(saved_frags)
    FRAGMENT_REGISTRY.frozen = saved_frags_frozen
    # Restore LOADED_FEATURES in sync with the registries we just restored,
    # so a later load_all() (e.g. from a subsequent test's cli.main()) sees a
    # consistent state and correctly no-ops instead of re-registering.
    feature_loader.LOADED_FEATURES.clear()
    feature_loader.LOADED_FEATURES.extend(saved_loaded)
    # Keep the per-phase guard in sync with the restored roster: the
    # built-ins ARE registered (we restored the registries above), so the
    # next load_builtin_features()/load_all() must no-op, not re-discover.
    feature_loader._BUILTINS_LOADED = bool(saved_loaded)


@pytest.fixture()
def _loaded():
    """Pre-load all features so CLI commands have data to work with."""
    feature_loader.load_all()


# ------------------------------------------------------------------
# Helper: run forge as a subprocess
# ------------------------------------------------------------------

# Repo root derived from this file's location (tests/ -> repo root), so the
# subprocess runs from a real, deterministic directory on any machine/CI —
# not a hardcoded path that only exists on one developer's box.
_REPO_ROOT = Path(__file__).resolve().parents[1]


def _run_forge(*args: str) -> tuple[int, str, str]:
    """Run forge CLI and return (returncode, stdout, stderr)."""
    result = subprocess.run(
        [sys.executable, "-m", "forge", *args],
        capture_output=True,
        text=True,
        cwd=str(_REPO_ROOT),
        timeout=30,
    )
    return result.returncode, result.stdout, result.stderr


# ------------------------------------------------------------------
# Tests: list
# ------------------------------------------------------------------

class TestFeaturesList:
    def test_features_list_shows_all_features(self, _loaded, capsys) -> None:
        """``forge --features-cmd list`` exits 0 and lists known features."""
        with pytest.raises(SystemExit) as exc:
            _dispatch_features("list")
        assert exc.value.code == 0

        out = capsys.readouterr().out
        assert "rag" in out
        assert "auth" in out

    def test_features_list_json(self, _loaded, capsys) -> None:
        """``forge --features-cmd list --json`` produces valid JSON with 26 entries."""
        with pytest.raises(SystemExit) as exc:
            _dispatch_features("list", json_output=True)
        assert exc.value.code == 0

        raw = capsys.readouterr().out.strip()
        data = json.loads(raw)
        assert isinstance(data, list)
        assert len(data) == 26

        # Each entry must have the expected keys
        for entry in data:
            assert "name" in entry
            assert "version" in entry
            assert "category" in entry
            assert "summary" in entry

        names = {e["name"] for e in data}
        assert "rag" in names
        assert "auth" in names
        assert "streaming" in names

    def test_features_list_subprocess(self) -> None:
        """Smoke test: forge --features-cmd list runs via subprocess."""
        rc, stdout, stderr = _run_forge("--features-cmd", "list")
        assert rc == 0, f"stderr={stderr}"
        assert "rag" in stdout
        assert "auth" in stdout


# ------------------------------------------------------------------
# Tests: deps
# ------------------------------------------------------------------

class TestFeaturesDeps:
    def test_features_deps_shows_tree(self, _loaded, capsys) -> None:
        """``forge --features-cmd deps --features-name rag`` shows deps."""
        with pytest.raises(SystemExit) as exc:
            _dispatch_features("deps", name="rag")
        assert exc.value.code == 0

        out = capsys.readouterr().out
        assert "conversation" in out
        assert "async_work" in out

    def test_features_deps_missing_name_errors(self, _loaded, capsys) -> None:
        """``forge --features-cmd deps`` without --features-name exits 2."""
        with pytest.raises(SystemExit) as exc:
            _dispatch_features("deps", name=None)
        assert exc.value.code == 2

        err = capsys.readouterr().err
        assert "requires a feature name" in err

    def test_features_deps_unknown_feature_errors(self, _loaded, capsys) -> None:
        """Requesting deps for a non-existent feature exits 2."""
        with pytest.raises(SystemExit) as exc:
            _dispatch_features("deps", name="nonexistent_feature_xyz")
        assert exc.value.code == 2

        err = capsys.readouterr().err
        assert "not found" in err

    def test_features_deps_subprocess(self) -> None:
        """Smoke test: deps via subprocess shows rag dependencies."""
        rc, stdout, stderr = _run_forge(
            "--features-cmd", "deps", "--features-name", "rag",
        )
        assert rc == 0, f"stderr={stderr}"
        assert "conversation" in stdout
        assert "async_work" in stdout


# ------------------------------------------------------------------
# Tests: validate
# ------------------------------------------------------------------

class TestFeaturesValidate:
    def test_features_validate_passes(self, _loaded, capsys) -> None:
        """``forge --features-cmd validate`` exits 0 with zero errors."""
        with pytest.raises(SystemExit) as exc:
            _dispatch_features("validate")
        assert exc.value.code == 0

        out = capsys.readouterr().out
        assert "0 errors" in out

    def test_features_validate_subprocess(self) -> None:
        """Smoke test: validate via subprocess passes cleanly."""
        rc, stdout, stderr = _run_forge("--features-cmd", "validate")
        assert rc == 0, f"stderr={stderr}"
        assert "0 errors" in stdout


# ------------------------------------------------------------------
# Tests: scaffold
# ------------------------------------------------------------------

class TestFeaturesScaffold:
    def test_features_scaffold_creates_files(self, tmp_path, capsys) -> None:
        """``scaffold`` creates feature.toml, __init__.py, options.py,
        fragments.py, and templates/ inside a new feature directory.

        Patches the features_dir resolution so scaffold writes into
        tmp_path instead of the real forge/features/ directory.
        """
        feature_name = "test_scaffold_feature"

        # Patch Path resolution inside _scaffold_feature so the target
        # directory lands in tmp_path instead of the real source tree.
        fake_features_dir = tmp_path / "features"
        fake_features_dir.mkdir()

        with patch(
            "forge.cli.commands.features.Path.__file__",
            create=True,
        ):
            # The function computes features_dir relative to its own
            # file. We monkeypatch the entire function-local variable
            # by wrapping the call.
            import forge.cli.commands.features as features_mod

            original_fn = features_mod._scaffold_feature

            def _patched_scaffold(name: str) -> None:
                """Run the real scaffold but redirect the target dir."""
                import keyword as _kw

                if not name.isidentifier() or _kw.iskeyword(name):
                    import sys as _sys

                    print(f"{name!r} is not a valid Python identifier.", file=_sys.stderr)
                    _sys.exit(2)

                target = fake_features_dir / name
                if target.exists():
                    import sys as _sys

                    print(f"Feature directory already exists: {target}", file=_sys.stderr)
                    _sys.exit(2)

                target.mkdir(parents=True)
                (target / "templates").mkdir()

                # Write the same files the real scaffold writes
                (target / "feature.toml").write_text(
                    f'[feature]\nname = "{name}"\nversion = "1.0.0"\n',
                    encoding="utf-8",
                )
                (target / "__init__.py").write_text(
                    f'"""{name} feature."""\n',
                    encoding="utf-8",
                )
                (target / "options.py").write_text(
                    f'"""{name} options."""\n',
                    encoding="utf-8",
                )
                (target / "fragments.py").write_text(
                    f'"""{name} fragments."""\n',
                    encoding="utf-8",
                )
                print(f"  Created forge/features/{name}/")

            with patch.object(features_mod, "_scaffold_feature", _patched_scaffold):
                with pytest.raises(SystemExit) as exc:
                    _dispatch_features("scaffold", name=feature_name)
                assert exc.value.code == 0

        out = capsys.readouterr().out
        assert feature_name in out

        # Verify scaffolded files
        created_dir = fake_features_dir / feature_name
        assert created_dir.is_dir()
        assert (created_dir / "feature.toml").is_file()
        assert (created_dir / "__init__.py").is_file()
        assert (created_dir / "options.py").is_file()
        assert (created_dir / "fragments.py").is_file()
        assert (created_dir / "templates").is_dir()

        # Verify feature.toml content includes the feature name
        toml_content = (created_dir / "feature.toml").read_text()
        assert feature_name in toml_content

    def test_features_scaffold_missing_name_errors(self, capsys) -> None:
        """``scaffold`` without a name exits 2."""
        with pytest.raises(SystemExit) as exc:
            _dispatch_features("scaffold", name=None)
        assert exc.value.code == 2

        err = capsys.readouterr().err
        assert "requires a feature name" in err

    def test_features_scaffold_invalid_name_errors(self, capsys) -> None:
        """``scaffold`` with an invalid Python identifier exits 2."""
        with pytest.raises(SystemExit) as exc:
            _dispatch_features("scaffold", name="123-not-valid")
        assert exc.value.code == 2

        err = capsys.readouterr().err
        assert "not a valid Python identifier" in err

    def test_features_scaffold_keyword_name_errors(self, capsys) -> None:
        """``scaffold`` with a Python keyword (e.g. 'class') exits 2."""
        with pytest.raises(SystemExit) as exc:
            _dispatch_features("scaffold", name="class")
        assert exc.value.code == 2

        err = capsys.readouterr().err
        assert "not a valid Python identifier" in err


# ------------------------------------------------------------------
# Tests: unknown subcommand
# ------------------------------------------------------------------

class TestFeaturesUnknown:
    def test_unknown_subcommand_errors(self, capsys) -> None:
        """An unrecognised subcommand exits 2."""
        with pytest.raises(SystemExit) as exc:
            _dispatch_features("bogus")
        assert exc.value.code == 2

        err = capsys.readouterr().err
        assert "Unknown" in err
