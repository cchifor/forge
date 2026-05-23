"""Structural tests for ``tests/mutmut_baselines.json``.

The scoped PR-gate (see ``.github/workflows/mutmut.yml`` job
``pr_gate``) consumes the ``pr_gate_modules`` block; this test pins
its shape so a refactor of the baselines file can't silently break
the gate.

Scope here is deliberately structural — kill-rate floors themselves
are out of scope (CI re-measures them each run and compares against
the floor). What we lock in is:

* the three required scoped modules are present (no silent
  removal — a removed key means "no gate" for that module, which
  is the exact regression we're guarding against),
* every floor is a float in ``[0.0, 1.0]`` (a non-float or an
  out-of-range value would crash ``mutmut_pr_gate.py`` or quietly
  pass every PR),
* every referenced source path exists on disk (catches a
  rename-without-baseline-update; the rename should land in the
  same PR that updates the baseline key).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
BASELINES_PATH = REPO_ROOT / "tests" / "mutmut_baselines.json"

# Mirrors the scoped subset choice in
# `Mutation-testing PR-gate scoped subset` (see plan). Three highest-
# blast-radius modules: every backend codegen path flows through the
# capability resolver; the sync resolver decides bidirectional file
# placement; provenance is the round-trip source of truth.
REQUIRED_SCOPED_MODULES = (
    "forge/capability_resolver.py",
    "forge/sync/forge_to_project/resolver/__init__.py",
    "forge/sync/provenance.py",
)


@pytest.fixture(scope="module")
def baselines() -> dict:
    return json.loads(BASELINES_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def pr_gate(baselines: dict) -> dict:
    assert "pr_gate_modules" in baselines, (
        "tests/mutmut_baselines.json must declare a ``pr_gate_modules`` "
        "block; the scoped PR-gate workflow reads from it."
    )
    return baselines["pr_gate_modules"]


def test_pr_gate_modules_has_required_keys(pr_gate: dict) -> None:
    """The three highest-blast-radius modules must always be gated.

    Removing a key would silently drop the gate for that module; pin
    the set so a refactor can't accidentally widen the velocity-policy
    scope or narrow it without an explicit baseline update.
    """
    missing = sorted(set(REQUIRED_SCOPED_MODULES) - pr_gate.keys())
    extra = sorted(pr_gate.keys() - set(REQUIRED_SCOPED_MODULES))
    assert not missing, (
        f"pr_gate_modules missing required keys: {missing}. "
        "These are the scoped PR-gate subset; removal needs a "
        "CHANGELOG entry + reviewer sign-off."
    )
    assert not extra, (
        f"pr_gate_modules has unexpected keys: {extra}. "
        "Widening the scoped subset is an Epic U scope change; "
        "either add the key here or update REQUIRED_SCOPED_MODULES "
        "in this test in the same PR."
    )


@pytest.mark.parametrize("module", REQUIRED_SCOPED_MODULES)
def test_pr_gate_floor_is_float_in_unit_interval(pr_gate: dict, module: str) -> None:
    """Each floor must be a real float in ``[0.0, 1.0]``.

    A non-float (e.g. ``int 1`` or ``str "0.85"``) or an out-of-range
    value would either crash ``mutmut_pr_gate.py`` on the comparison
    or quietly pass every PR — both are silent failures we want
    surfaced at edit time, not at PR-time.
    """
    floor = pr_gate[module]
    # ``bool`` is a subclass of ``int`` in Python — exclude it
    # explicitly to avoid ``True`` slipping through as ``1.0``.
    assert isinstance(floor, float) and not isinstance(floor, bool), (
        f"pr_gate_modules[{module!r}] must be a float, got {type(floor).__name__}={floor!r}"
    )
    assert 0.0 <= floor <= 1.0, (
        f"pr_gate_modules[{module!r}] = {floor!r} is outside [0.0, 1.0]; "
        "kill rates are fractions and a value outside this range is "
        "always either a typo or a misuse."
    )


@pytest.mark.parametrize("module", REQUIRED_SCOPED_MODULES)
def test_pr_gate_source_path_exists(module: str) -> None:
    """A baseline keyed on a renamed/deleted file is a silent skip.

    The PR-gate workflow only mutates files in ``pr_gate_modules`` that
    are also touched by the PR; if the file no longer exists on disk
    the gate becomes a permanent no-op for that key. Catch the
    rename-without-baseline-update in the same PR.
    """
    target = REPO_ROOT / module
    assert target.is_file(), (
        f"pr_gate_modules references {module!r} but {target} does not "
        "exist on disk. If the module was renamed, update the key in "
        "the same PR."
    )
