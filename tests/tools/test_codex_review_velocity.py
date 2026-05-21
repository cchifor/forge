"""Smoke tests for ``tools/codex_review_velocity.py``.

The tool is dependency-free and operates on the live git history; these
tests exercise its CLI surface end-to-end against the current repo
(running ``python tools/codex_review_velocity.py`` in a subprocess) and
also unit-test the pure-function summary path against fabricated inputs.

Justification for not isolating from real git history: the tool's whole
purpose is to read ``git log``, and stubbing git would mostly re-implement
the tool. Instead we run it for a wide window (365 days) so the answer
is stable across short-term commit churn and assert structural properties
rather than exact numbers.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TOOL = REPO_ROOT / "tools" / "codex_review_velocity.py"


def _run(args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(TOOL), *args],
        cwd=cwd or REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_tool_exists_and_is_executable_via_python():
    assert TOOL.is_file(), f"tool missing: {TOOL}"


def test_json_output_shape():
    result = _run(["--since", "365", "--json"])
    assert result.returncode in (0, 1), result.stderr
    data = json.loads(result.stdout)
    for key in (
        "window_days",
        "pr_count",
        "round_total",
        "round_median",
        "round_max",
        "round_p95",
        "prs_over_two_rounds",
    ):
        assert key in data, f"missing key {key} in {data}"
    assert data["window_days"] == 365
    assert isinstance(data["pr_count"], int)
    assert isinstance(data["round_total"], int)
    assert data["pr_count"] >= 0
    assert isinstance(data["prs_over_two_rounds"], list)


def test_text_output_default():
    result = _run(["--since", "30"])
    assert result.returncode in (0, 1), result.stderr
    assert "Codex review velocity" in result.stdout
    assert "Merged PRs:" in result.stdout


def test_strict_exit_codes_with_zero_history():
    # Window of 0 days → no merged PRs → median is 0 → strict still exits 0.
    result = _run(["--since", "0", "--json", "--strict"])
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["pr_count"] == 0


def test_summarize_pure_function_handles_empty_input():
    sys.path.insert(0, str(REPO_ROOT))
    try:
        # Importing the tool as a module — its filename has no extension
        # issues; load it via importlib for robustness.
        import importlib.util

        spec = importlib.util.spec_from_file_location("codex_velocity", TOOL)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        summary = module._summarize([], window_days=30)
    finally:
        sys.path.pop(0)
    assert summary == {
        "window_days": 30,
        "pr_count": 0,
        "round_total": 0,
        "round_median": 0,
        "round_max": 0,
        "round_p95": 0,
        "prs_over_two_rounds": [],
    }


def test_missing_branch_returns_empty_result():
    """CI checkouts often lack `main` as a local ref (shallow / detached HEAD).

    The tool must treat that as zero merged PRs rather than crashing —
    measurement should never block CI on environmental shape.
    """
    result = _run(["--branch", "nonexistent-branch-name", "--since", "30", "--json"])
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["pr_count"] == 0
    assert data["round_total"] == 0


def test_summarize_pure_function_with_synthetic_data():
    import importlib.util

    spec = importlib.util.spec_from_file_location("codex_velocity_b", TOOL)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    summary = module._summarize(
        [(101, 1), (102, 2), (103, 3), (104, 0), (105, 1)],
        window_days=14,
    )
    assert summary["pr_count"] == 5
    assert summary["round_total"] == 7
    assert summary["round_median"] == 1
    assert summary["round_max"] == 3
    assert summary["prs_over_two_rounds"] == [103]
