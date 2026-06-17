"""#258 — fuzz over ``--platform`` preset combinations.

``tests/fuzz/test_fragment_combinations.py`` fuzzes the resolver over random
*option* combinations but never exercises the platform presets, so a broken
preset (e.g. the multitenant-saas TMS boot regression) could ship without a
fuzz signal. This module:

1. Deterministically resolves **every** registered preset (a fast smoke that
   fails loudly the moment a preset stops building a consistent plan).
2. Fuzzes each preset under random option perturbations — the preset is the
   lowest-priority layer, so user options layered on top must still resolve to
   a consistent plan (or fail validation cleanly, never crash the resolver).
"""

from __future__ import annotations

import argparse

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from forge.capability_resolver import resolve
from forge.cli.builder import _build_config
from forge.cli.parser import _build_parser
from forge.errors import OptionsError
from forge.options import OPTION_REGISTRY, OptionType
from forge.platform_templates import available_platform_templates

pytestmark = pytest.mark.fuzz

_PRESETS = sorted(available_platform_templates())

# Boolean + enum options are safe to perturb without inventing malformed
# values; invalid *combinations* (e.g. a DB-backed toggle under
# database.mode=none) are expected to fail validation cleanly and are skipped.
_BOOL_OPTIONS = sorted(
    p for p, o in OPTION_REGISTRY.items() if o.type is OptionType.BOOL
)
_ENUM_OPTIONS = sorted(
    p for p, o in OPTION_REGISTRY.items() if o.type is OptionType.ENUM and o.options
)


def _config_from_preset(preset_name: str | None, options: dict[str, object] | None):
    """Build a ProjectConfig the way ``forge --platform <name>`` would.

    Uses the real parser defaults so every arg the builder reads is populated,
    then drives the preset + option overrides through the CLI config builder.
    """
    ns: argparse.Namespace = _build_parser().parse_args([])
    ns.platform = preset_name
    cfg: dict[str, object] = {}
    if options:
        cfg["options"] = dict(options)
    return _build_config(ns, cfg)


def _assert_plan_is_consistent(plan) -> None:
    """Invariants every resolved plan must satisfy (mirrors the resolver fuzzer)."""
    names = {rf.fragment.name for rf in plan.ordered}
    for rf in plan.ordered:
        missing = [d for d in rf.fragment.depends_on if d not in names]
        assert not missing, (
            f"fragment {rf.fragment.name!r} depends on {missing} absent from the plan"
        )
        conflicts = set(rf.fragment.conflicts_with) & names
        assert not conflicts, (
            f"fragment {rf.fragment.name!r} conflicts with {sorted(conflicts)} in-plan"
        )
    claimed: set[str] = set()
    for rf in plan.ordered:
        claimed.update(rf.fragment.capabilities)
    extra = set(plan.capabilities) - claimed
    assert not extra, f"plan.capabilities {extra} not sourced from any fragment"


@pytest.mark.parametrize("preset", _PRESETS)
def test_every_preset_resolves_consistently(preset: str) -> None:
    """Each shipped preset must build + validate + resolve to a consistent plan."""
    config = _config_from_preset(preset, None)
    config.validate()
    plan = resolve(config)
    _assert_plan_is_consistent(plan)
    assert config.backends, f"preset {preset!r} produced no backends"
    assert plan.ordered, f"preset {preset!r} resolved to an empty fragment plan"


@settings(
    deadline=None,
    max_examples=60,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.filter_too_much],
)
@given(data=st.data())
def test_preset_with_perturbed_options_resolves(data: st.DataObject) -> None:
    """A preset + random option overrides resolves consistently, or fails
    validation cleanly — the resolver must never raise an unhandled error."""
    preset = data.draw(st.sampled_from([None, *_PRESETS]))

    overrides: dict[str, object] = {}
    for path in data.draw(
        st.lists(st.sampled_from(_BOOL_OPTIONS), max_size=4, unique=True)
    ):
        overrides[path] = data.draw(st.booleans())
    for path in data.draw(
        st.lists(st.sampled_from(_ENUM_OPTIONS), max_size=3, unique=True)
    ):
        overrides[path] = data.draw(st.sampled_from(OPTION_REGISTRY[path].options))

    try:
        config = _config_from_preset(preset, overrides)
        config.validate()
    except (OptionsError, ValueError):
        # Invalid combination — rejected before generation, as designed.
        return

    plan = resolve(config)
    _assert_plan_is_consistent(plan)
