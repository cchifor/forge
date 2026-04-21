"""Tests for the TypeScript anchor injector (I8)."""

from __future__ import annotations

from pathlib import Path

import pytest

from forge.errors import InjectionError
from forge.injectors.ts_ast import inject_ts


class TestInjectTs:
    def test_fresh_injection_at_legacy_marker(self, tmp_path: Path) -> None:
        src = tmp_path / "app.ts"
        src.write_text(
            "export function buildApp() {\n"
            "  const app = fastify();\n"
            "  // FORGE:MIDDLEWARE\n"
            "  return app;\n"
            "}\n",
            encoding="utf-8",
        )
        inject_ts(src, "rate_limit", "MIDDLEWARE", "app.register(rateLimit);", "after")
        body = src.read_text(encoding="utf-8")
        assert "// FORGE:BEGIN rate_limit:MIDDLEWARE" in body
        assert "app.register(rateLimit);" in body

    def test_fresh_injection_at_anchor_comment(self, tmp_path: Path) -> None:
        src = tmp_path / "main.ts"
        src.write_text(
            "export function buildApp() {\n"
            "  // forge:anchor middleware.registration\n"
            "  return app;\n"
            "}\n",
            encoding="utf-8",
        )
        inject_ts(src, "rate_limit", "middleware.registration", "app.register(rateLimit);", "after")
        body = src.read_text(encoding="utf-8")
        assert "// FORGE:BEGIN rate_limit:middleware.registration" in body
        assert "app.register(rateLimit);" in body

    def test_idempotent_reapply(self, tmp_path: Path) -> None:
        src = tmp_path / "app.ts"
        src.write_text(
            "export function buildApp() {\n"
            "  // FORGE:M\n"
            "  return app;\n"
            "}\n",
            encoding="utf-8",
        )
        inject_ts(src, "rl", "M", "const v1 = 1;", "after")
        inject_ts(src, "rl", "M", "const v2 = 2;", "after")
        body = src.read_text(encoding="utf-8")
        assert body.count("// FORGE:BEGIN rl:M") == 1
        assert "const v1 = 1" not in body
        assert "const v2 = 2" in body

    def test_preserves_indentation(self, tmp_path: Path) -> None:
        src = tmp_path / "app.ts"
        src.write_text(
            "class App {\n"
            "    configure() {\n"
            "        // FORGE:HOOKS\n"
            "        return this;\n"
            "    }\n"
            "}\n",
            encoding="utf-8",
        )
        inject_ts(src, "plugin", "HOOKS", "this.registerHook();", "after")
        body = src.read_text(encoding="utf-8")
        assert "        this.registerHook();" in body

    def test_anchor_must_be_unique(self, tmp_path: Path) -> None:
        src = tmp_path / "app.ts"
        src.write_text(
            "// forge:anchor dup\n"
            "const a = 1;\n"
            "// forge:anchor dup\n"
            "const b = 2;\n",
            encoding="utf-8",
        )
        with pytest.raises(InjectionError, match="multiple lines"):
            inject_ts(src, "f", "dup", "const x = 0;", "after")

    def test_missing_anchor_raises(self, tmp_path: Path) -> None:
        src = tmp_path / "app.ts"
        src.write_text("export const x = 1;\n", encoding="utf-8")
        with pytest.raises(InjectionError, match="not found"):
            inject_ts(src, "f", "NO_SUCH", "const y = 2;", "after")

    def test_position_before(self, tmp_path: Path) -> None:
        src = tmp_path / "app.ts"
        src.write_text(
            "export function app() {\n"
            "  // FORGE:REG\n"
            "  return null;\n"
            "}\n",
            encoding="utf-8",
        )
        inject_ts(src, "f", "REG", "const v = 1;", "before")
        body = src.read_text(encoding="utf-8")
        begin_line = None
        marker_line = None
        for i, line in enumerate(body.splitlines()):
            if "// FORGE:BEGIN f:REG" in line:
                begin_line = i
            if "// FORGE:REG" in line and "BEGIN" not in line and "END" not in line:
                marker_line = i
        assert begin_line is not None and marker_line is not None
        assert begin_line < marker_line


class TestFeatureInjectorDispatch:
    """Dispatch selects the right injector based on file extension."""

    def test_ts_file_uses_ts_injector(self, tmp_path: Path) -> None:
        src = tmp_path / "app.ts"
        src.write_text("// FORGE:X\nconst a = 1;\n", encoding="utf-8")
        from forge.feature_injector import _Injection, _dispatch_injector  # noqa: PLC0415

        inj = _Injection(
            feature_key="f",
            target="app.ts",
            marker="X",
            snippet="const b = 2;",
            position="after",
            zone="generated",
        )
        _dispatch_injector(src, inj)
        body = src.read_text(encoding="utf-8")
        assert "// FORGE:BEGIN f:X" in body
        assert "const b = 2" in body

    def test_py_file_uses_python_injector(self, tmp_path: Path) -> None:
        src = tmp_path / "main.py"
        src.write_text("# FORGE:Y\npass\n", encoding="utf-8")
        from forge.feature_injector import _Injection, _dispatch_injector  # noqa: PLC0415

        inj = _Injection(
            feature_key="f",
            target="main.py",
            marker="Y",
            snippet="import os",
            position="after",
            zone="generated",
        )
        _dispatch_injector(src, inj)
        body = src.read_text(encoding="utf-8")
        assert "# FORGE:BEGIN f:Y" in body
        assert "import os" in body
