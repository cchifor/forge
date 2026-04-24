"""Fuzz tests for the resolver (P2.4).

Forge ships ~100+ options with combinatorial interactions via
``Option.enables``, ``Fragment.depends_on``, and
``Fragment.conflicts_with``. Hand-written tests cover a finite list of
presets (python-vue, node-svelte, ...); this module randomizes option
sets and verifies the resolver:

1. Always terminates (no infinite loops in the dep graph).
2. Either produces a valid plan or raises :class:`OptionsError`.
3. Never produces a plan that contains a conflict pair.
4. Never produces a plan with a dangling ``depends_on`` (a required
   fragment missing from the plan).

Hypothesis drives the random generation. The test is registered under
a ``fuzz`` marker so it can be opted out of the fast suite and run
nightly instead.
"""

from __future__ import annotations

import pytest
from hypothesis import HealthCheck, given, settings, strategies as st

from forge.capability_resolver import resolve
from forge.config import BackendConfig, BackendLanguage, ProjectConfig
from forge.errors import OptionsError
from forge.fragments import FRAGMENT_REGISTRY
from forge.options import OPTION_REGISTRY, OptionType

pytestmark = pytest.mark.fuzz


def _option_value_strategy(option):
    """Return a Hypothesis strategy that produces values of this option's type.

    We sample realistically-typed values so the resolver doesn't reject
    everything at coercion. Unknown / exotic option types fall back to
    the option's registered default.
    """
    if option.type == OptionType.BOOL:
        return st.booleans()
    if option.type == OptionType.ENUM:
        choices = list(getattr(option, "choices", ()) or ())
        if choices:
            return st.sampled_from(choices)
        return st.just(option.default)
    if option.type == OptionType.INT:
        return st.integers(min_value=0, max_value=1000)
    if option.type == OptionType.STRING:
        return st.text(alphabet="abcdef0123456789-_", min_size=1, max_size=10)
    return st.just(option.default)


_BOOL_ENUM_OPTIONS = [
    opt
    for opt in OPTION_REGISTRY.values()
    if opt.type in (OptionType.BOOL, OptionType.ENUM)
]


@st.composite
def random_project_config(draw):
    """Generate a :class:`ProjectConfig` with a random subset of bool/enum
    options set. Keeps the generator tractable by not perturbing int
    / string options (which rarely produce resolver conflicts)."""
    sample_size = draw(st.integers(min_value=0, max_value=min(20, len(_BOOL_ENUM_OPTIONS))))
    chosen = draw(
        st.lists(
            st.sampled_from(_BOOL_ENUM_OPTIONS) if _BOOL_ENUM_OPTIONS else st.nothing(),
            min_size=sample_size,
            max_size=sample_size,
            unique_by=lambda o: o.path,
        )
    )
    option_values: dict[str, object] = {}
    for option in chosen:
        option_values[option.path] = draw(_option_value_strategy(option))

    language = draw(
        st.sampled_from(
            [
                BackendLanguage.PYTHON,
                BackendLanguage.NODE,
                BackendLanguage.RUST,
            ]
        )
    )
    return ProjectConfig(
        project_name="fuzz",
        backends=[
            BackendConfig(
                name="api",
                language=language,
                features=["items"],
                server_port=5000,
                description="fuzz backend",
            )
        ],
        options=option_values,
    )


@settings(
    deadline=None,
    max_examples=75,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.filter_too_much],
)
@given(config=random_project_config())
def test_resolve_either_succeeds_cleanly_or_raises_options_error(config):
    """The resolver must terminate on every random input and either
    return a plan or raise :class:`OptionsError`. Any other exception
    is a bug."""
    try:
        plan = resolve(config)
    except OptionsError:
        return  # expected for invalid combinations
    _assert_plan_is_consistent(plan)


def _assert_plan_is_consistent(plan) -> None:
    """Invariants every returned plan must satisfy."""
    names = {rf.fragment.name for rf in plan.ordered}
    # All declared depends_on must be present in the plan.
    for rf in plan.ordered:
        missing = [d for d in rf.fragment.depends_on if d not in names]
        assert not missing, (
            f"fragment {rf.fragment.name!r} depends on {missing} which are "
            "absent from the resolved plan"
        )
    # No pair in the plan may conflict.
    for rf in plan.ordered:
        conflicts = set(rf.fragment.conflicts_with) & names
        assert not conflicts, (
            f"fragment {rf.fragment.name!r} conflicts with {sorted(conflicts)} "
            "but both ended up in the plan"
        )
    # Capabilities should match the fragments in the plan.
    claimed = set()
    for rf in plan.ordered:
        claimed.update(rf.fragment.capabilities)
    extra = set(plan.capabilities) - claimed
    assert not extra, (
        f"plan.capabilities contains {extra} not sourced from any fragment"
    )


@pytest.mark.parametrize(
    "fragment_name",
    sorted(FRAGMENT_REGISTRY.keys()),
)
def test_every_registered_fragment_has_non_empty_implementations(fragment_name):
    """Cheap parametric sanity check — catches a fragment accidentally
    registered with an empty impl dict."""
    fragment = FRAGMENT_REGISTRY[fragment_name]
    assert fragment.implementations, (
        f"fragment {fragment_name!r} has no implementations"
    )
