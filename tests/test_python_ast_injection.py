"""Tests for AST-based Python injection (2.1 of the 1.0 roadmap)."""

from __future__ import annotations

from pathlib import Path

import pytest

from forge.errors import InjectionError
from forge.injectors.python_ast import inject_python


class TestInjectPython:
    def test_fresh_injection_at_legacy_marker(self, tmp_path: Path) -> None:
        src = tmp_path / "main.py"
        src.write_text(
            "def create_app():\n"
            "    app = FastAPI()\n"
            "    # FORGE:MIDDLEWARE_IMPORTS\n"
            "    return app\n",
            encoding="utf-8",
        )
        inject_python(src, "rate_limit", "MIDDLEWARE_IMPORTS", "import x\nimport y", "after")
        body = src.read_text(encoding="utf-8")
        assert "# FORGE:BEGIN rate_limit:MIDDLEWARE_IMPORTS" in body
        assert "import x" in body
        assert "import y" in body
        assert "# FORGE:END rate_limit:MIDDLEWARE_IMPORTS" in body

    def test_fresh_injection_at_anchor_comment(self, tmp_path: Path) -> None:
        src = tmp_path / "main.py"
        src.write_text(
            "def create_app():\n"
            "    # forge:anchor middleware.imports\n"
            "    return app\n",
            encoding="utf-8",
        )
        inject_python(src, "rate_limit", "middleware.imports", "import x", "after")
        body = src.read_text(encoding="utf-8")
        assert "# FORGE:BEGIN rate_limit:middleware.imports" in body
        assert "import x" in body

    def test_idempotent_reapply_replaces_block(self, tmp_path: Path) -> None:
        src = tmp_path / "main.py"
        src.write_text(
            "def create_app():\n"
            "    # FORGE:M\n"
            "    return app\n",
            encoding="utf-8",
        )
        inject_python(src, "rate_limit", "M", "import v1", "after")
        before = src.read_text(encoding="utf-8")
        inject_python(src, "rate_limit", "M", "import v2", "after")
        after = src.read_text(encoding="utf-8")
        assert before.count("# FORGE:BEGIN rate_limit:M") == 1
        assert after.count("# FORGE:BEGIN rate_limit:M") == 1
        assert "import v1" not in after
        assert "import v2" in after

    def test_preserves_indentation(self, tmp_path: Path) -> None:
        src = tmp_path / "main.py"
        src.write_text(
            "class App:\n"
            "    def configure(self):\n"
            "        # FORGE:HOOKS\n"
            "        return None\n",
            encoding="utf-8",
        )
        inject_python(src, "plugin", "HOOKS", "self.register_hook()", "after")
        body = src.read_text(encoding="utf-8")
        # The snippet should carry the 8-space indent from the marker line.
        assert "        self.register_hook()" in body

    def test_anchor_must_be_unique(self, tmp_path: Path) -> None:
        src = tmp_path / "main.py"
        src.write_text(
            "# forge:anchor dup\n"
            "pass\n"
            "# forge:anchor dup\n"
            "pass\n",
            encoding="utf-8",
        )
        with pytest.raises(InjectionError, match="multiple lines"):
            inject_python(src, "f", "dup", "x", "after")

    def test_missing_anchor_raises(self, tmp_path: Path) -> None:
        src = tmp_path / "main.py"
        src.write_text("def app():\n    return None\n", encoding="utf-8")
        with pytest.raises(InjectionError, match="not found"):
            inject_python(src, "f", "NO_SUCH", "x", "after")

    def test_reformat_surviving_anchor(self, tmp_path: Path) -> None:
        """After applying a fragment, reformatting the file and reapplying
        should still find the anchor via the BEGIN sentinel (not the raw
        marker text, which may have moved)."""
        src = tmp_path / "main.py"
        src.write_text(
            "def app():\n"
            "    # FORGE:X\n"
            "    return None\n",
            encoding="utf-8",
        )
        inject_python(src, "f", "X", "import a", "after")

        # Simulate a reformat: user runs ruff format and lines get reflowed.
        # The sentinel block should still be findable verbatim.
        body = src.read_text(encoding="utf-8")
        # Add an unrelated comment above to mimic a reformat tool's behavior.
        reformatted = body.replace(
            "def app():\n", "# Unrelated user comment added by formatter\ndef app():\n"
        )
        src.write_text(reformatted, encoding="utf-8")

        # Re-apply — this should update in place, not duplicate.
        inject_python(src, "f", "X", "import b", "after")
        final = src.read_text(encoding="utf-8")
        assert final.count("# FORGE:BEGIN f:X") == 1
        assert "import a" not in final
        assert "import b" in final

    def test_position_before(self, tmp_path: Path) -> None:
        src = tmp_path / "main.py"
        src.write_text(
            "def app():\n"
            "    # FORGE:REG\n"
            "    return None\n",
            encoding="utf-8",
        )
        inject_python(src, "f", "REG", "import a", "before")
        body = src.read_text(encoding="utf-8")
        # The BEGIN block should appear BEFORE the marker line.
        begin_line = None
        marker_line = None
        for i, line in enumerate(body.splitlines()):
            if "# FORGE:BEGIN f:REG" in line:
                begin_line = i
            if "# FORGE:REG" in line and "BEGIN" not in line and "END" not in line:
                marker_line = i
        assert begin_line is not None and marker_line is not None
        assert begin_line < marker_line

    def test_syntactic_error_fallback_to_text(self, tmp_path: Path) -> None:
        # A file with a syntax error — libcst will fail to parse; we
        # should still inject via the text fallback.
        src = tmp_path / "broken.py"
        src.write_text(
            "def app(\n"  # invalid Python
            "    # FORGE:X\n"
            "    return None\n",
            encoding="utf-8",
        )
        inject_python(src, "f", "X", "import a", "after")
        assert "# FORGE:BEGIN f:X" in src.read_text(encoding="utf-8")
