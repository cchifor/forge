"""Assert ``docs/FEATURES.md`` option catalog matches the live ``OPTION_REGISTRY``.

The catalog block in ``docs/FEATURES.md`` (between the BEGIN /
END markers) is generated from ``OPTION_REGISTRY`` by
``tools/gen_features_doc.py``. This test fails when the file on
disk has drifted from what the generator would produce — typically
because someone added or modified an option without rerunning the
generator.

When this test fails, the fix is::

    uv run python tools/gen_features_doc.py

then commit the resulting ``docs/FEATURES.md`` change.

This is the doc-side counterpart to the registry invariants in
``tests/test_options.py``: that file enforces the registry stays
internally consistent; this file enforces the documentation stays
in lock-step with it.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
TOOLS_DIR = REPO_ROOT / "tools"

# tools/ is a script directory, not a Python package — add it to sys.path
# so we can import the generator. Mirrors how a maintainer runs it via
# ``uv run python tools/gen_features_doc.py``.
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))


def test_features_doc_in_sync() -> None:
    """``docs/FEATURES.md`` is byte-identical to what the generator emits."""
    import gen_features_doc  # noqa: PLC0415

    current = gen_features_doc.FEATURES_DOC.read_text(encoding="utf-8")
    generated_body = gen_features_doc.render_catalog()
    expected = gen_features_doc.replace_in_features_doc(current, generated_body)

    if current == expected:
        return

    pytest.fail(
        "docs/FEATURES.md is out of sync with OPTION_REGISTRY.\n"
        "Run: uv run python tools/gen_features_doc.py\n"
        "then commit the resulting docs/FEATURES.md change.\n\n"
        "(The catalog block between the BEGIN/END markers is auto-generated "
        "from forge/options/_registry.py and forge/features/<ns>/options.py — "
        "do not hand-edit it.)"
    )


def test_features_doc_markers_present() -> None:
    """Sanity: the BEGIN/END markers are still on disk so the generator can find them."""
    import gen_features_doc  # noqa: PLC0415

    text = gen_features_doc.FEATURES_DOC.read_text(encoding="utf-8")
    assert gen_features_doc.BEGIN_MARKER in text, (
        "BEGIN marker missing from docs/FEATURES.md. The generator can't "
        "find the auto-section. Re-add the markers."
    )
    assert gen_features_doc.END_MARKER in text, (
        "END marker missing from docs/FEATURES.md. The generator can't "
        "find the auto-section. Re-add the markers."
    )
