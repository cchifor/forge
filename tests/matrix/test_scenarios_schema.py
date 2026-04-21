"""Schema validation for ``tests/matrix/scenarios.yaml``.

Guards three invariants the runner (``tests/matrix/runner.py``) relies
on:

1. Every scenario has a unique ``name`` and a distinct ``port_base``.
2. Every referenced lane is one of ``generate`` / ``verify`` / ``smoke``.
3. Every scenario's ``config`` block can be materialized into a
   :class:`forge.config.ProjectConfig` via the runner's shared builder
   path — i.e. the matrix can't ship a scenario that forge itself
   refuses to parse.

These run on every PR (cheap, ~1 second) so a bad merge into
``scenarios.yaml`` fails CI without waiting for lane A's generate
step.
"""

from __future__ import annotations

import pytest

from tests.matrix.runner import (
    ALL_LANES,
    Scenario,
    _project_config_from_dict,
    load_scenarios,
)


@pytest.fixture(scope="module")
def scenarios() -> list[Scenario]:
    return load_scenarios()


def test_at_least_one_scenario(scenarios: list[Scenario]) -> None:
    assert len(scenarios) >= 1


def test_names_unique(scenarios: list[Scenario]) -> None:
    names = [s.name for s in scenarios]
    assert len(names) == len(set(names))


def test_port_bases_unique_and_spaced(scenarios: list[Scenario]) -> None:
    """Adjacent scenarios must be at least 10 ports apart so each can
    occupy ``[port_base, port_base + 9]`` without colliding with its
    neighbor. Keeps lane C's compose-up runs parallelizable."""
    ports = sorted(s.port_base for s in scenarios)
    for a, b in zip(ports, ports[1:], strict=False):
        assert b - a >= 10, f"ports {a} and {b} are less than 10 apart"


def test_lanes_are_known(scenarios: list[Scenario]) -> None:
    for sc in scenarios:
        for lane in sc.lanes:
            assert lane in ALL_LANES


def test_every_config_builds(scenarios: list[Scenario]) -> None:
    """Each scenario's ``config`` must round-trip through the CLI
    builder + ``ProjectConfig.validate``. Catches schema drift between
    the matrix and what forge actually accepts."""
    for sc in scenarios:
        cfg_copy = dict(sc.config)
        cfg_copy.setdefault("output_dir", ".")
        project_config = _project_config_from_dict(cfg_copy)
        project_config.validate()


def test_expected_files_is_non_empty_for_every_scenario(scenarios: list[Scenario]) -> None:
    """A scenario without expected files would silently pass lane A
    regardless of what forge produced — defeats the point."""
    for sc in scenarios:
        assert sc.expected_files, f"scenario {sc.name!r} has empty expected_files"
