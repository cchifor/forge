"""Unit tests for ``scripts/coverage_badge.py``.

The script runs in CI after the coverage job. These tests exercise
its tiny surface directly (no subprocess) so a broken script surfaces
with a line number rather than a cryptic CI failure.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

# The script isn't part of the ``forge`` package — load it from its
# file path so this test doesn't depend on ``scripts/`` being a
# sys.path entry.
SCRIPT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "coverage_badge.py"


@pytest.fixture
def badge_module():
    spec = importlib.util.spec_from_file_location("_coverage_badge_under_test", SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_coverage_json(path: Path, pct: float) -> None:
    path.write_text(
        json.dumps({"totals": {"percent_covered": pct}}, indent=2),
        encoding="utf-8",
    )


def test_read_coverage_percent_success(badge_module, tmp_path: Path) -> None:
    cov = tmp_path / "coverage.json"
    _write_coverage_json(cov, 83.5)
    assert badge_module._read_coverage_percent(cov) == 83.5


def test_read_coverage_percent_missing_file(badge_module, tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        badge_module._read_coverage_percent(tmp_path / "no-such.json")


def test_read_coverage_percent_missing_totals(badge_module, tmp_path: Path) -> None:
    cov = tmp_path / "coverage.json"
    cov.write_text(json.dumps({"wrong": "shape"}), encoding="utf-8")
    with pytest.raises(ValueError, match="totals"):
        badge_module._read_coverage_percent(cov)


def test_write_badge_json(badge_module, tmp_path: Path) -> None:
    out = tmp_path / ".forge-coverage.json"
    badge_module._write_badge_json(83.51, out)
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["percent_covered"] == 83.51
    assert payload["display"] == "83.5%"
    assert "updated_at" in payload


def test_refresh_policy_doc_inserts_block_when_missing(
    badge_module, tmp_path: Path
) -> None:
    doc = tmp_path / "coverage-policy.md"
    doc.write_text("# Coverage Policy\n\nIntro paragraph.\n", encoding="utf-8")
    badge_module._refresh_policy_doc(83.5, doc)
    text = doc.read_text(encoding="utf-8")
    assert "<!-- COVERAGE-BADGE:START -->" in text
    assert "<!-- COVERAGE-BADGE:END -->" in text
    assert "83.5%" in text
    assert "Intro paragraph." in text  # original content preserved


def test_refresh_policy_doc_replaces_existing_block(
    badge_module, tmp_path: Path
) -> None:
    doc = tmp_path / "coverage-policy.md"
    doc.write_text(
        "# Coverage Policy\n\n"
        "<!-- COVERAGE-BADGE:START -->\nold content 50.0%\n<!-- COVERAGE-BADGE:END -->\n\n"
        "Body\n",
        encoding="utf-8",
    )
    badge_module._refresh_policy_doc(84.2, doc)
    text = doc.read_text(encoding="utf-8")
    assert "50.0%" not in text
    assert "84.2%" in text
    assert "Body" in text
    # Exactly one block — regression guard against the sub() accidentally
    # duplicating when markers are malformed.
    assert text.count("<!-- COVERAGE-BADGE:START -->") == 1


def test_refresh_policy_doc_creates_parent_dir(badge_module, tmp_path: Path) -> None:
    doc = tmp_path / "new_subdir" / "coverage-policy.md"
    badge_module._refresh_policy_doc(90.0, doc)
    assert doc.exists()
    assert "90.0%" in doc.read_text(encoding="utf-8")
