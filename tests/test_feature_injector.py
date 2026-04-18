"""Tests for feature_injector: snippet insertion, dep edits, env vars, file copy."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import tomlkit

from forge.capability_resolver import ResolvedFeature
from forge.config import BackendConfig, BackendLanguage
from forge.errors import GeneratorError
from forge.feature_injector import (
    _add_env_var,
    _add_node_deps,
    _add_python_deps,
    _add_rust_deps,
    _copy_files,
    _inject_snippet,
    apply_features,
)
from forge.features import FeatureConfig, FeatureSpec, FragmentImplSpec


# -- _inject_snippet ----------------------------------------------------------


class TestInjectSnippet:
    def _write(self, tmp_path: Path, content: str, name: str = "main.py") -> Path:
        file = tmp_path / name
        file.write_text(content, encoding="utf-8")
        return file

    def test_after_marker_inserts_below(self, tmp_path) -> None:
        file = self._write(tmp_path, "foo\n# FORGE:X\nbar\n")
        _inject_snippet(file, "feat_a", "FORGE:X", "mid", "after")
        text = file.read_text(encoding="utf-8")
        assert text == (
            "foo\n"
            "# FORGE:X\n"
            "# FORGE:BEGIN feat_a:X\n"
            "mid\n"
            "# FORGE:END feat_a:X\n"
            "bar\n"
        )

    def test_before_marker_inserts_above(self, tmp_path) -> None:
        file = self._write(tmp_path, "foo\n# FORGE:X\nbar\n")
        _inject_snippet(file, "feat_a", "FORGE:X", "mid", "before")
        text = file.read_text(encoding="utf-8")
        assert text == (
            "foo\n"
            "# FORGE:BEGIN feat_a:X\n"
            "mid\n"
            "# FORGE:END feat_a:X\n"
            "# FORGE:X\n"
            "bar\n"
        )

    def test_preserves_marker_indentation(self, tmp_path) -> None:
        file = self._write(tmp_path, "def f():\n    # FORGE:X\n    return 1\n")
        _inject_snippet(file, "feat_a", "FORGE:X", "step()", "after")
        text = file.read_text(encoding="utf-8")
        # Sentinels + snippet all inherit the marker's 4-space indent.
        assert "    # FORGE:BEGIN feat_a:X\n" in text
        assert "    step()\n" in text
        assert "    # FORGE:END feat_a:X\n" in text

    def test_multi_line_snippet(self, tmp_path) -> None:
        file = self._write(tmp_path, "  # FORGE:A\n")
        _inject_snippet(file, "feat_a", "FORGE:A", "line1\nline2", "after")
        text = file.read_text(encoding="utf-8")
        assert "  line1\n  line2\n" in text

    def test_missing_marker_raises(self, tmp_path) -> None:
        file = self._write(tmp_path, "nothing here\n")
        with pytest.raises(GeneratorError, match="not found"):
            _inject_snippet(file, "feat_a", "FORGE:MISSING", "x", "after")

    def test_duplicate_marker_raises(self, tmp_path) -> None:
        file = self._write(tmp_path, "# FORGE:X\n# FORGE:X\n")
        with pytest.raises(GeneratorError, match="appears 2 times"):
            _inject_snippet(file, "feat_a", "FORGE:X", "x", "after")

    def test_auto_prepends_forge_prefix(self, tmp_path) -> None:
        file = self._write(tmp_path, "# FORGE:Y\n")
        # Marker passed without the FORGE: prefix should still resolve.
        _inject_snippet(file, "feat_a", "Y", "ok", "after")
        assert "ok" in file.read_text(encoding="utf-8")

    def test_missing_target_file_raises(self, tmp_path) -> None:
        with pytest.raises(GeneratorError, match="not found"):
            _inject_snippet(tmp_path / "ghost.py", "feat_a", "FORGE:X", "x", "after")

    # --- Idempotency + re-injection -----------------------------------------

    def test_rerun_same_feature_replaces_in_place(self, tmp_path) -> None:
        """Re-running with the same feature_key/marker replaces the block,
        not duplicate. This is the B2.3 unlock for `forge update`.
        """
        file = self._write(tmp_path, "pre\n# FORGE:X\npost\n")
        _inject_snippet(file, "feat_a", "FORGE:X", "v1", "after")
        _inject_snippet(file, "feat_a", "FORGE:X", "v2", "after")
        text = file.read_text(encoding="utf-8")
        # The new body replaces the old; only one BEGIN/END pair exists.
        assert text.count("# FORGE:BEGIN feat_a:X") == 1
        assert text.count("# FORGE:END feat_a:X") == 1
        assert "v1" not in text
        assert "v2\n" in text

    def test_different_features_coexist(self, tmp_path) -> None:
        """Two different features inject around the same marker without collision."""
        file = self._write(tmp_path, "pre\n# FORGE:X\npost\n")
        _inject_snippet(file, "feat_a", "FORGE:X", "from_a", "after")
        _inject_snippet(file, "feat_b", "FORGE:X", "from_b", "after")
        text = file.read_text(encoding="utf-8")
        assert "# FORGE:BEGIN feat_a:X" in text
        assert "# FORGE:BEGIN feat_b:X" in text
        assert "from_a" in text
        assert "from_b" in text

    def test_typescript_uses_slash_comments(self, tmp_path) -> None:
        file = self._write(tmp_path, "line\n// FORGE:X\nend\n", name="main.ts")
        _inject_snippet(file, "feat_a", "FORGE:X", "console.log('ok');", "after")
        text = file.read_text(encoding="utf-8")
        assert "// FORGE:BEGIN feat_a:X\n" in text
        assert "// FORGE:END feat_a:X\n" in text

    def test_rust_uses_slash_comments(self, tmp_path) -> None:
        file = self._write(tmp_path, "line\n// FORGE:X\nend\n", name="main.rs")
        _inject_snippet(file, "feat_a", "FORGE:X", "println!(\"ok\");", "after")
        text = file.read_text(encoding="utf-8")
        assert "// FORGE:BEGIN feat_a:X\n" in text

    def test_missing_end_sentinel_raises(self, tmp_path) -> None:
        """A BEGIN without matching END signals a corrupt/hand-edited file."""
        file = self._write(
            tmp_path,
            "pre\n# FORGE:X\n# FORGE:BEGIN feat_a:X\nold\n# no end here\npost\n",
        )
        with pytest.raises(GeneratorError, match="END.*missing"):
            _inject_snippet(file, "feat_a", "FORGE:X", "new", "after")


# -- _add_python_deps ---------------------------------------------------------


class TestAddPythonDeps:
    def _pyproject(self, tmp_path: Path, deps: list[str]) -> Path:
        file = tmp_path / "pyproject.toml"
        content = "[project]\nname = \"x\"\nversion = \"0.1\"\ndependencies = [\n"
        for d in deps:
            content += f'    "{d}",\n'
        content += "]\n"
        file.write_text(content, encoding="utf-8")
        return file

    def test_appends_new_dep(self, tmp_path) -> None:
        pyproject = self._pyproject(tmp_path, ["fastapi>=0.115"])
        _add_python_deps(pyproject, ("slowapi>=0.1.9",))
        parsed = tomlkit.parse(pyproject.read_text(encoding="utf-8"))
        deps = list(parsed["project"]["dependencies"])
        assert "slowapi>=0.1.9" in deps
        assert "fastapi>=0.115" in deps

    def test_idempotent(self, tmp_path) -> None:
        pyproject = self._pyproject(tmp_path, ["slowapi>=0.1.9"])
        _add_python_deps(pyproject, ("slowapi>=0.1.9",))
        parsed = tomlkit.parse(pyproject.read_text(encoding="utf-8"))
        deps = [str(d) for d in parsed["project"]["dependencies"]]
        assert deps.count("slowapi>=0.1.9") == 1

    def test_missing_pyproject_raises(self, tmp_path) -> None:
        with pytest.raises(GeneratorError, match="pyproject.toml not found"):
            _add_python_deps(tmp_path / "ghost.toml", ("x",))

    def test_no_project_section_raises(self, tmp_path) -> None:
        file = tmp_path / "pyproject.toml"
        file.write_text("[tool.ruff]\nline-length = 100\n", encoding="utf-8")
        with pytest.raises(GeneratorError, match="missing"):
            _add_python_deps(file, ("x",))


# -- _add_node_deps -----------------------------------------------------------


class TestAddNodeDeps:
    def test_appends_plain_dep(self, tmp_path) -> None:
        pkg = tmp_path / "package.json"
        pkg.write_text(json.dumps({"name": "x", "dependencies": {}}), encoding="utf-8")
        _add_node_deps(pkg, ("fastify@5.0.0",))
        data = json.loads(pkg.read_text(encoding="utf-8"))
        assert data["dependencies"]["fastify"] == "5.0.0"

    def test_scoped_package(self, tmp_path) -> None:
        pkg = tmp_path / "package.json"
        pkg.write_text(json.dumps({"name": "x"}), encoding="utf-8")
        _add_node_deps(pkg, ("@fastify/rate-limit@10.0.0",))
        data = json.loads(pkg.read_text(encoding="utf-8"))
        assert data["dependencies"]["@fastify/rate-limit"] == "10.0.0"

    def test_idempotent(self, tmp_path) -> None:
        pkg = tmp_path / "package.json"
        pkg.write_text(
            json.dumps({"name": "x", "dependencies": {"fastify": "5.0.0"}}),
            encoding="utf-8",
        )
        _add_node_deps(pkg, ("fastify@6.0.0",))
        # Existing version wins — no clobber.
        data = json.loads(pkg.read_text(encoding="utf-8"))
        assert data["dependencies"]["fastify"] == "5.0.0"


# -- _add_rust_deps -----------------------------------------------------------


class TestAddRustDeps:
    def test_appends(self, tmp_path) -> None:
        cargo = tmp_path / "Cargo.toml"
        cargo.write_text(
            '[package]\nname = "x"\nversion = "0.1"\n\n[dependencies]\naxum = "0.8"\n',
            encoding="utf-8",
        )
        _add_rust_deps(cargo, ("tower@0.5",))
        parsed = tomlkit.parse(cargo.read_text(encoding="utf-8"))
        assert parsed["dependencies"]["tower"] == "0.5"
        assert parsed["dependencies"]["axum"] == "0.8"

    def test_full_toml_with_features(self, tmp_path) -> None:
        cargo = tmp_path / "Cargo.toml"
        cargo.write_text('[package]\nname = "x"\nversion = "0.1"\n\n[dependencies]\n', encoding="utf-8")
        _add_rust_deps(
            cargo,
            ('opentelemetry-otlp = { version = "0.27", features = ["grpc-tonic"] }',),
        )
        parsed = tomlkit.parse(cargo.read_text(encoding="utf-8"))
        entry = parsed["dependencies"]["opentelemetry-otlp"]
        assert dict(entry) == {"version": "0.27", "features": ["grpc-tonic"]}

    def test_mixed_shorthand_and_full(self, tmp_path) -> None:
        cargo = tmp_path / "Cargo.toml"
        cargo.write_text('[package]\nname = "x"\nversion = "0.1"\n\n[dependencies]\n', encoding="utf-8")
        _add_rust_deps(
            cargo,
            (
                "hmac@0.12",
                'sha2 = { version = "0.10", default-features = false }',
                "reqwest@0.12",
            ),
        )
        parsed = tomlkit.parse(cargo.read_text(encoding="utf-8"))
        assert parsed["dependencies"]["hmac"] == "0.12"
        assert dict(parsed["dependencies"]["sha2"]) == {
            "version": "0.10",
            "default-features": False,
        }
        assert parsed["dependencies"]["reqwest"] == "0.12"

    def test_bad_toml_value_raises(self, tmp_path) -> None:
        cargo = tmp_path / "Cargo.toml"
        cargo.write_text('[package]\nname = "x"\nversion = "0.1"\n\n[dependencies]\n', encoding="utf-8")
        with pytest.raises(GeneratorError, match="bad Rust dep value"):
            _add_rust_deps(cargo, ("broken = { version = }",))


# -- _add_env_var -------------------------------------------------------------


class TestAddEnvVar:
    def test_creates_file(self, tmp_path) -> None:
        env = tmp_path / ".env.example"
        _add_env_var(env, "KEY", "value")
        assert env.read_text(encoding="utf-8") == "KEY=value\n"

    def test_appends_idempotently(self, tmp_path) -> None:
        env = tmp_path / ".env.example"
        env.write_text("EXISTING=yes\n", encoding="utf-8")
        _add_env_var(env, "NEW", "v")
        _add_env_var(env, "NEW", "v")  # second call: no-op
        text = env.read_text(encoding="utf-8")
        assert text.count("NEW=v\n") == 1

    def test_adds_trailing_newline_if_missing(self, tmp_path) -> None:
        env = tmp_path / ".env.example"
        env.write_text("A=1", encoding="utf-8")  # no trailing newline
        _add_env_var(env, "B", "2")
        assert env.read_text(encoding="utf-8") == "A=1\nB=2\n"


# -- _copy_files --------------------------------------------------------------


class TestCopyFiles:
    def test_copies_nested_structure(self, tmp_path) -> None:
        src = tmp_path / "src"
        (src / "nested" / "deep").mkdir(parents=True)
        (src / "a.py").write_text("print('a')\n", encoding="utf-8")
        (src / "nested" / "b.py").write_text("print('b')\n", encoding="utf-8")
        (src / "nested" / "deep" / "c.py").write_text("print('c')\n", encoding="utf-8")

        dst = tmp_path / "dst"
        dst.mkdir()
        _copy_files(src, dst)

        assert (dst / "a.py").read_text(encoding="utf-8") == "print('a')\n"
        assert (dst / "nested" / "b.py").exists()
        assert (dst / "nested" / "deep" / "c.py").exists()

    def test_refuses_to_overwrite(self, tmp_path) -> None:
        src = tmp_path / "src"
        src.mkdir()
        (src / "a.py").write_text("new\n", encoding="utf-8")
        dst = tmp_path / "dst"
        dst.mkdir()
        (dst / "a.py").write_text("existing\n", encoding="utf-8")
        with pytest.raises(GeneratorError, match="tried to overwrite"):
            _copy_files(src, dst)


# -- apply_features orchestration --------------------------------------------


class TestApplyFeatures:
    def test_skips_feature_for_unsupported_backend(self, tmp_path) -> None:
        # Construct a fake feature that only supports Rust, then try to apply to a Python backend.
        spec = FeatureSpec(
            key="rust_only",
            display_label="rust only",
            cli_flag="--x",
            implementations={BackendLanguage.RUST: FragmentImplSpec(fragment_dir="rust_only/rust")},
        )
        resolved = (
            ResolvedFeature(
                spec=spec, config=FeatureConfig(enabled=True), target_backends=(BackendLanguage.RUST,)
            ),
        )
        bc = BackendConfig(name="svc", project_name="P", language=BackendLanguage.PYTHON)
        # Should be a no-op — no exception raised.
        apply_features(bc, tmp_path, resolved, quiet=True)

    def test_correlation_id_fragment_end_to_end(self, tmp_path) -> None:
        """End-to-end check of the real correlation_id fragment.

        Builds a minimal backend directory with the two markers the fragment
        expects, runs apply_features for the real registry entry, and asserts
        both the import and the registration were injected, plus the middleware
        file was copied into place.
        """
        from forge.features import FEATURE_REGISTRY

        # Stub out a minimal src/app/main.py that mimics the base template's markers.
        app_dir = tmp_path / "src" / "app"
        app_dir.mkdir(parents=True)
        (app_dir / "main.py").write_text(
            "# imports\n"
            "# FORGE:MIDDLEWARE_IMPORTS\n"
            "\n"
            "def _configure_middleware(app):\n"
            "    # FORGE:MIDDLEWARE_REGISTRATION\n"
            "    pass\n",
            encoding="utf-8",
        )

        spec = FEATURE_REGISTRY["correlation_id"]
        resolved = (
            ResolvedFeature(
                spec=spec,
                config=FeatureConfig(enabled=True),
                target_backends=(BackendLanguage.PYTHON,),
            ),
        )
        bc = BackendConfig(name="api", project_name="P", language=BackendLanguage.PYTHON)
        apply_features(bc, tmp_path, resolved, quiet=True)

        main_py = (tmp_path / "src" / "app" / "main.py").read_text(encoding="utf-8")
        assert "from app.middleware.correlation import CorrelationIdMiddleware" in main_py
        assert "app.add_middleware(CorrelationIdMiddleware)" in main_py

        middleware_file = tmp_path / "src" / "app" / "middleware" / "correlation.py"
        assert middleware_file.is_file()
        assert "class CorrelationIdMiddleware" in middleware_file.read_text(encoding="utf-8")
