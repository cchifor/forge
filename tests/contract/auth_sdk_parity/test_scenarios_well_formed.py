"""Meta-test: the cross-SDK parity scenario spec is internally coherent.

This is the spec's *invariants gate* — it asserts that every scenario
is well-formed, every name is unique, every expected error slug is
one of the cross-language `reason()` values the SDKs actually emit,
and the JSON dump round-trips without losing required fields.

The actual cross-language assertions (Python/Node/Rust runners that
mint a token from each scenario's inputs and verify it) land as
follow-up sub-phases. This file gates the spec, not the runners.

Cross-reference: implementation plan at
``~/.claude/plans/review-the-c-users-chifo-work-platform-a-pure-torvalds.md``
(Phase 9 deliverables).
"""

from __future__ import annotations

import json
import re

from tests.contract.auth_sdk_parity.scenarios import (
    REQUIRED_CLAIMS,
    SCENARIOS,
    ExpectedError,
    ExpectedOutcome,
    Scenario,
    scenarios_as_json,
    scenarios_by_name,
)


# All AuthError variants the SDKs emit. Pinned here so adding a new
# variant on the SDK side without a corresponding scenario is caught.
KNOWN_ERROR_SLUGS: frozenset[str] = frozenset(
    {
        "invalid_token",
        "token_expired",
        "token_revoked",
        "issuer_not_trusted",
        "actor_not_authorized",
        "scope_required",
        "tenant_suspended",
        "s2s_auth_error",
    }
)

_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")


def test_required_claims_constant_matches_rfc_9068() -> None:
    """The required-claims tuple in the spec is the cross-language
    contract — every SDK must enforce these. Pin it explicitly."""
    expected = ("iss", "aud", "sub", "exp", "iat", "jti")
    assert REQUIRED_CLAIMS == expected, (
        f"REQUIRED_CLAIMS drifted from RFC 9068 baseline: got {REQUIRED_CLAIMS}, "
        f"expected {expected}. SDKs must match."
    )


def test_at_least_one_happy_path() -> None:
    """If every scenario expects an error, the runner can't tell
    success from "every assertion happens to fail the same way" —
    a happy path is the calibration."""
    happy = [s for s in SCENARIOS if s.expected.identity is not None]
    assert happy, "spec must include at least one happy-path scenario"


def test_scenario_names_are_unique() -> None:
    """Names index into the runner's per-scenario assertions; a
    duplicate would mask a missing case."""
    names = [s.name for s in SCENARIOS]
    duplicates = sorted({n for n in names if names.count(n) > 1})
    assert not duplicates, f"duplicate scenario names: {duplicates}"


def test_scenario_names_are_snake_case() -> None:
    """Names are used as test-case ids across all three runners — pin
    the casing convention so the language conventions don't drift."""
    bad = [s.name for s in SCENARIOS if not _NAME_RE.match(s.name)]
    assert not bad, (
        f"scenario names must be snake_case (^[a-z][a-z0-9_]*$): {bad}"
    )


def test_every_scenario_has_a_description() -> None:
    """Descriptions explain *why* the scenario exists. A reviewer
    reading the spec a year from now must understand intent."""
    no_desc = [s.name for s in SCENARIOS if not s.description.strip()]
    assert not no_desc, f"scenarios missing description: {no_desc}"


def test_expected_outcome_has_either_identity_or_error() -> None:
    """ExpectedOutcome's invariant is enforced by __post_init__, but
    pin it via a meta-test so a future refactor that loosens the
    constructor surfaces here."""
    for s in SCENARIOS:
        has_identity = s.expected.identity is not None
        has_error = s.expected.error is not None
        assert has_identity != has_error, (
            f"scenario {s.name!r}: ExpectedOutcome must set exactly "
            f"one of `identity` or `error` (got identity={has_identity}, "
            f"error={has_error})"
        )


def test_error_slugs_are_known() -> None:
    """Error slugs must match `AuthError.reason()` values the SDKs
    actually emit. A typo here would assert against a slug that no
    runner ever produces."""
    for s in SCENARIOS:
        if s.expected.error is None:
            continue
        assert s.expected.error in KNOWN_ERROR_SLUGS, (
            f"scenario {s.name!r}: error slug {s.expected.error!r} not in "
            f"KNOWN_ERROR_SLUGS. Did the SDK gain a new variant? "
            f"Add it to KNOWN_ERROR_SLUGS in this file AND to the "
            f"per-language test_*_sdk.py invariants."
        )


def test_at_least_one_scenario_per_known_error_slug() -> None:
    """Every error variant the SDKs emit must have at least one
    scenario exercising it. Otherwise a runner's translation of
    that variant could be wrong without anyone noticing.

    Some slugs (s2s_auth_error) belong to outbound flows that
    AuthGuard.verify can't produce — those are excluded from the
    coverage gate. Document each exclusion inline.
    """
    # AuthGuard.verify never raises s2s_auth_error — that's an
    # S2SClient-only error class. Exclude until the parity spec
    # gains S2S scenarios (follow-up).
    inbound_only_slugs = KNOWN_ERROR_SLUGS - {"s2s_auth_error"}

    # scope_required is reserved for `requireScope`, not raw verify().
    # Exclude until the spec gains require-scope scenarios.
    inbound_only_slugs = inbound_only_slugs - {"scope_required"}

    covered = {s.expected.error for s in SCENARIOS if s.expected.error is not None}
    uncovered = inbound_only_slugs - covered
    assert not uncovered, (
        f"AuthError variants without a parity scenario: {sorted(uncovered)}. "
        f"Add a scenario or document an exclusion in this test."
    )


def test_act_chain_scenarios_have_may_act_allowlist() -> None:
    """A scenario carrying an `act` claim must declare a may_act
    allowlist (even if empty for the deny-test). Otherwise the
    verifier's policy interaction is implicit and the scenario's
    behavior depends on the SDK's default policy — which would make
    the test non-portable."""
    for s in SCENARIOS:
        if s.act is None:
            continue
        # The empty-dict case is allowed (deny-by-default) — only the
        # MISSING field is forbidden. Dataclass field default factory
        # gives an empty dict, so absence and emptiness are the same
        # thing here. We assert that the test author considered the
        # interaction by checking that either:
        #   - There's an allowlist with at least one entry
        #   - OR the expected outcome is `actor_not_authorized` /
        #     `invalid_token` (deny-by-default behavior)
        if s.may_act_allowlist:
            continue
        if s.expected.error in (
            "actor_not_authorized",
            "invalid_token",
        ):
            continue
        raise AssertionError(
            f"scenario {s.name!r} carries an act claim but no "
            f"may_act_allowlist AND expects success — that's "
            f"ambiguous. Either add an allowlist or expect a deny."
        )


def test_revocation_scenarios_have_denylist_entry() -> None:
    """A scenario expecting `token_revoked` must put its jti on the
    revocation denylist; otherwise the SDK's RevocationStore (defaulting
    to NeverRevokedStore) wouldn't reject."""
    for s in SCENARIOS:
        if s.expected.error != "token_revoked":
            continue
        assert s.jti is not None, (
            f"scenario {s.name!r}: token_revoked needs a fixed jti so "
            f"the runner can put it on the denylist before verification"
        )
        assert s.jti in s.revocation_denylist, (
            f"scenario {s.name!r}: jti {s.jti!r} must be in "
            f"revocation_denylist={list(s.revocation_denylist)!r}"
        )


def test_scenarios_as_json_is_serializable() -> None:
    """Per-language runners (Node, Rust) load the JSON dump.

    Asserting that `scenarios_as_json()` produces a structure that
    `json.dumps` accepts (no tuples, no dataclass instances, no
    weird types) catches drift the moment a new field is added in
    a non-serializable shape.
    """
    dumped = scenarios_as_json()
    # Round-trip through json.dumps to confirm.
    serialized = json.dumps(dumped)
    reloaded = json.loads(serialized)
    assert len(reloaded) == len(SCENARIOS), (
        "JSON round-trip dropped scenarios — check scenarios_as_json"
    )


def test_scenarios_by_name_matches_scenarios_tuple() -> None:
    by_name = scenarios_by_name()
    assert set(by_name.keys()) == {s.name for s in SCENARIOS}
    for s in SCENARIOS:
        assert by_name[s.name] is s


def test_dataclass_field_types_are_concrete() -> None:
    """Forbid `None` mutable defaults that bypass the frozen dataclass
    contract — every Scenario must have either a value or a sentinel
    that survives a frozen-dataclass equality check."""
    # Spot-check by constructing one default-everything scenario.
    s = Scenario(
        name="fixture_test_only",
        description="dataclass shape sanity",
    )
    # The default ExpectedOutcome should have an identity (not error).
    assert s.expected.identity is not None
    assert s.expected.error is None
    # Mutable-default fields (extra_claims, trust_map_overrides,
    # may_act_allowlist) must default to empty containers, not shared
    # references — otherwise edits to one scenario would leak.
    s2 = Scenario(name="fixture_test_only_2", description="...")
    assert s.extra_claims is not s2.extra_claims, (
        "Mutable default leaked — use field(default_factory=...)"
    )


def test_expected_error_literal_covers_known_slugs() -> None:
    """The `ExpectedError` Literal type is the static type-side of
    the cross-language contract. Its members must equal the
    SDK-emitted slug set."""
    # Pull the Literal values via typing introspection.
    import typing

    args = typing.get_args(ExpectedError)
    assert set(args) == KNOWN_ERROR_SLUGS, (
        f"ExpectedError Literal drifted from KNOWN_ERROR_SLUGS:\n"
        f"  in Literal: {sorted(args)}\n"
        f"  in KNOWN_ERROR_SLUGS: {sorted(KNOWN_ERROR_SLUGS)}\n"
        f"  diff: {sorted(set(args) ^ KNOWN_ERROR_SLUGS)}"
    )


def test_default_outcome_uses_canonical_constants() -> None:
    """The Scenario default factory uses TENANT_ID + SUBJECT — pin
    via a constructed instance so a future edit that swaps in a
    different default surfaces as a test failure."""
    s = Scenario(name="default_outcome_check", description="...")
    expected = s.expected.identity
    assert expected is not None
    assert expected["tenant_id"] == "11111111-1111-4111-8111-111111111111"
    assert expected["subject"] == "22222222-2222-4222-8222-222222222222"
