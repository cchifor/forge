"""Per-module coverage gate (Epic S, 1.1.0-alpha.1).

Two layers of coverage gating, by design:

1. **Project-wide floor** lives in ``pyproject.toml`` as ``fail_under``.
   Coarse safety net across every module.
2. **Critical-path per-module floors** live here, in ``MODULE_FLOORS``. The
   modules in this table are the ones where a silent coverage regression
   would ship to every generated project on the next ``forge --update``.

Every CI run produces ``coverage.json`` via ``pytest --cov-report=json``. This
test parses that report and fails when any listed module drops below its
floor. When ``coverage.json`` isn't present (e.g. a developer ran a focused
subset locally), the test is skipped with a helpful hint.

See ``docs/coverage-policy.md`` for the ratchet policy — floors move
upward each sprint; lowering any of them requires a CHANGELOG note +
RFC-002 justification.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import NamedTuple

import pytest


class ModuleGate(NamedTuple):
    """A coverage floor + target for one critical-path module."""

    floor_pct: float
    target_pct: float

    def __repr__(self) -> str:  # pragma: no cover
        return f"ModuleGate(floor={self.floor_pct}%, target={self.target_pct}%)"


# Floors are the minimum acceptable coverage today; targets are the steady
# state we're ratcheting toward across 1.x. Keep this table in sync with
# docs/coverage-policy.md — the CI gate reads this dict, the docs are
# human-facing, and drift between them is a review blocker.
# Calibration note (Epic S, 1.1.0-alpha.1): measured baseline was
#   capability_resolver=97.0%  feature_injector=90.0%  merge=86.7%
#   provenance=96.7%  python_ast=97.8%  ts_ast=97.3%  updater=80.5%
# The floor values below are measured - 2pp so a small incidental drop
# doesn't block an unrelated PR. Targets represent the steady state we
# aim for across 1.x. See docs/coverage-policy.md for the ratchet rules.
MODULE_FLOORS: dict[str, ModuleGate] = {
    "forge/capability_resolver.py": ModuleGate(floor_pct=95.0, target_pct=98.0),
    "forge/feature_injector.py": ModuleGate(floor_pct=88.0, target_pct=95.0),
    "forge/merge.py": ModuleGate(floor_pct=85.0, target_pct=95.0),
    "forge/provenance.py": ModuleGate(floor_pct=95.0, target_pct=98.0),
    "forge/injectors/python_ast.py": ModuleGate(floor_pct=95.0, target_pct=98.0),
    "forge/injectors/ts_ast.py": ModuleGate(floor_pct=95.0, target_pct=98.0),
    "forge/updater.py": ModuleGate(floor_pct=78.0, target_pct=90.0),
}


def _coverage_json_path() -> Path:
    """Locate the coverage.json report, preferring the repo-root default."""
    root = Path(__file__).resolve().parent.parent
    return root / "coverage.json"


def _load_per_file_coverage() -> dict[str, float]:
    """Return ``{relative_posix_path: covered_pct}`` from the coverage report.

    coverage.py writes JSON as ``{"files": {"<relpath>": {"summary": {...}}}}``.
    The relpaths use the platform's separator on write; normalize to POSIX so
    the MODULE_FLOORS keys match on Windows + Linux equally.
    """
    path = _coverage_json_path()
    if not path.is_file():
        pytest.skip(
            f"coverage.json not found at {path}; run `uv run pytest -m 'not e2e' "
            "--cov --cov-report=json:coverage.json` to produce it."
        )
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    out: dict[str, float] = {}
    for raw_path, entry in data.get("files", {}).items():
        summary = entry.get("summary", {})
        pct = summary.get("percent_covered")
        if pct is None:
            continue
        # coverage.py uses backslashes on Windows. Normalize to POSIX so
        # `forge/capability_resolver.py` matches regardless of the host.
        out[raw_path.replace("\\", "/")] = float(pct)
    return out


def test_module_floors_gate_has_entries() -> None:
    """Smoke test: the gate table must be non-empty — an empty gate is a
    silent regression of the regression detector itself.
    """
    assert MODULE_FLOORS, "MODULE_FLOORS is empty; the coverage gate is disabled"


def test_docs_table_stays_in_sync() -> None:
    """docs/coverage-policy.md lists the same modules as MODULE_FLOORS.

    Keeps the human-facing table and the test-enforced table from drifting.
    """
    policy = Path(__file__).resolve().parent.parent / "docs" / "coverage-policy.md"
    body = policy.read_text(encoding="utf-8")
    for module in MODULE_FLOORS:
        assert f"`{module}`" in body, (
            f"{module} is gated in MODULE_FLOORS but missing from "
            f"docs/coverage-policy.md — update the table."
        )


@pytest.mark.parametrize("module", list(MODULE_FLOORS.keys()))
def test_module_meets_floor(module: str) -> None:
    """Each critical-path module's coverage meets or exceeds its floor."""
    gate = MODULE_FLOORS[module]
    per_file = _load_per_file_coverage()
    actual = per_file.get(module)
    if actual is None:
        pytest.fail(
            f"No coverage data recorded for {module}. Either the module moved "
            f"(update MODULE_FLOORS + docs/coverage-policy.md) or the test "
            f"runner excluded it via [tool.coverage.run].omit."
        )
    assert actual >= gate.floor_pct, (
        f"{module} coverage {actual:.1f}% is below the floor of "
        f"{gate.floor_pct:.1f}% (target: {gate.target_pct:.1f}%). "
        "Either add tests or — if the drop is justified — lower the floor "
        "with a CHANGELOG entry per docs/coverage-policy.md."
    )
