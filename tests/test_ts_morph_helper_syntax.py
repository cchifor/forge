"""Guard that the ts-morph subprocess helper is valid JavaScript.

The helper (``forge/injectors/ts-morph-helper.mjs``) is the opt-in
``FORGE_TS_AST=1`` AST-injection path. If the module does not even parse,
``node`` exits non-zero on *every* invocation and the sidecar
(``ts_morph_sidecar.py``) silently degrades to the regex injector — a
100% dead feature that ``forge doctor`` cannot detect because it only
probes ``require('ts-morph')`` and the helper's *existence*, never that
it parses.

These tests pin the helper as parseable JS so a Python-ism (e.g. an
f-string ``!r`` conversion) cannot leak into the JS template literal
again.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

import forge

HELPER = Path(forge.__file__).parent / "injectors" / "ts-morph-helper.mjs"


def test_helper_file_exists() -> None:
    assert HELPER.is_file(), f"ts-morph helper missing: {HELPER}"


def test_helper_has_no_python_repr_conversion() -> None:
    """No ``!r}`` — that is Python f-string repr syntax, a SyntaxError in JS.

    Static check (runs even without Node) so CI lanes lacking Node still
    catch the regression.
    """
    text = HELPER.read_text(encoding="utf-8")
    assert "!r}" not in text, (
        "ts-morph-helper.mjs contains Python f-string repr syntax `!r}` "
        "inside a JS template literal — this is a SyntaxError that disables "
        "the entire FORGE_TS_AST path."
    )


@pytest.mark.skipif(shutil.which("node") is None, reason="node not on PATH")
def test_helper_passes_node_syntax_check() -> None:
    """``node --check`` must accept the helper (it parses as valid JS)."""
    proc = subprocess.run(
        ["node", "--check", str(HELPER)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, (
        f"ts-morph-helper.mjs failed `node --check`:\n{proc.stderr}"
    )
