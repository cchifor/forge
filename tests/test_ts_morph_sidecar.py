"""Tests for the ts-morph sidecar bridge (A2-5)."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from forge.injectors.ts_morph_sidecar import is_enabled, inject_ts_via_morph


class TestIsEnabled:
    def test_disabled_when_env_unset(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("FORGE_TS_AST", None)
            assert is_enabled() is False

    def test_disabled_when_env_false(self) -> None:
        with patch.dict(os.environ, {"FORGE_TS_AST": "0"}):
            assert is_enabled() is False

    def test_disabled_when_node_missing(self) -> None:
        with patch.dict(os.environ, {"FORGE_TS_AST": "1"}):
            with patch("shutil.which", return_value=None):
                assert is_enabled() is False


class TestInjectTsViaMorph:
    def test_disabled_returns_false(self, tmp_path: Path) -> None:
        src = tmp_path / "app.ts"
        src.write_text("// FORGE:X\nconst a = 1;\n", encoding="utf-8")
        with patch.dict(os.environ, {"FORGE_TS_AST": "0"}):
            result = inject_ts_via_morph(src, "f", "X", "const b = 2;", "after")
        assert result is False

    def test_timeout_returns_false(self, tmp_path: Path) -> None:
        import subprocess

        src = tmp_path / "app.ts"
        src.write_text("// FORGE:X\n", encoding="utf-8")
        with patch.dict(os.environ, {"FORGE_TS_AST": "1"}):
            with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("node", 15)):
                with patch("shutil.which", return_value="/usr/bin/node"):
                    result = inject_ts_via_morph(src, "f", "X", "x", "after")
        assert result is False


class TestFallback:
    def test_regex_injector_used_when_sidecar_unavailable(self, tmp_path: Path) -> None:
        """When FORGE_TS_AST=1 but ts-morph isn't installed, regex fallback still works."""
        from forge.injectors.ts_ast import inject_ts

        src = tmp_path / "app.ts"
        src.write_text("// FORGE:X\nconst a = 1;\n", encoding="utf-8")
        # Force-disabled path — sidecar returns False, regex takes over.
        with patch("forge.injectors.ts_morph_sidecar.is_enabled", return_value=False):
            inject_ts(src, "f", "X", "const b = 2;", "after")
        body = src.read_text(encoding="utf-8")
        assert "// FORGE:BEGIN f:X" in body
        assert "const b = 2;" in body
