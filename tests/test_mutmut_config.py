"""Regression: mutmut config + baselines must stay in sync with the live tree.

mutmut silently no-ops on missing paths, so a stale ``paths_to_mutate``
list looks like a healthy run while measuring nothing. The pre-Epic-A
modules ``forge/feature_injector.py``, ``forge/merge.py``,
``forge/provenance.py``, and ``forge/updater.py`` were decomposed into
``forge/sync/*`` and ``forge/appliers/*``; this module asserts the
post-decomposition layout is reflected in both the ``[tool.mutmut]``
table and ``tests/mutmut_baselines.json``.
"""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _paths_to_mutate() -> tuple[str, ...]:
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return tuple(pyproject["tool"]["mutmut"]["paths_to_mutate"])


def _baseline_modules() -> dict[str, dict[str, object]]:
    baselines = json.loads((REPO_ROOT / "tests/mutmut_baselines.json").read_text(encoding="utf-8"))
    return baselines["modules"]


def test_every_path_in_pyproject_exists_on_disk() -> None:
    for path in _paths_to_mutate():
        target = REPO_ROOT / path
        assert target.is_file(), (
            f"[tool.mutmut].paths_to_mutate references a missing file: {path}\n"
            "mutmut silently no-ops on missing paths — fix pyproject.toml or "
            "restore the file."
        )


def test_pyproject_and_baselines_cover_the_same_module_set() -> None:
    pyproject = set(_paths_to_mutate())
    baselines = set(_baseline_modules())
    only_in_pyproject = pyproject - baselines
    only_in_baselines = baselines - pyproject
    assert not only_in_pyproject, (
        f"paths_to_mutate has modules without a baseline budget: {sorted(only_in_pyproject)}"
    )
    assert not only_in_baselines, (
        f"mutmut_baselines.json has modules not in paths_to_mutate: {sorted(only_in_baselines)}"
    )


def test_every_baseline_has_required_budget_keys() -> None:
    for module, budget in _baseline_modules().items():
        assert "kill_rate_min" in budget, f"{module}: missing kill_rate_min"
        assert "survivors_max" in budget, f"{module}: missing survivors_max"
        kill_rate = budget["kill_rate_min"]
        survivors = budget["survivors_max"]
        assert isinstance(kill_rate, (int, float)) and 0 <= kill_rate <= 1, (
            f"{module}: kill_rate_min must be in [0, 1], got {kill_rate!r}"
        )
        assert isinstance(survivors, int) and survivors >= 0, (
            f"{module}: survivors_max must be a non-negative int, got {survivors!r}"
        )


def test_updater_aggregate_survivor_budget_matches_pre_decomposition_cap() -> None:
    """The pre-Epic-A ``forge/updater.py`` allowed at most 5 survivors;
    the decomposed package (``__init__.py``, ``_merge_driver.py``,
    ``_template_render.py``) must not exceed that aggregate cap, or the
    weekly mutation lane is implicitly looser than before the split.
    """
    baselines = _baseline_modules()
    updater_files = {
        m: budget["survivors_max"]
        for m, budget in baselines.items()
        if m.startswith("forge/sync/forge_to_project/updater/")
    }
    assert updater_files, "expected updater module budgets in baselines"
    aggregate = sum(updater_files.values())
    assert aggregate <= 5, (
        f"Aggregate updater survivor budget {aggregate} exceeds pre-Epic-A "
        f"cap of 5. Per-file budgets: {updater_files}. Either tighten "
        f"per-file caps or amend this test with an RFC-002 justification."
    )
