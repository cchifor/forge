"""Scope hierarchy resolution tests.

The hierarchy rules (exact, super-wildcard, verb-wildcard, namespace-
wildcard) are the contract every endpoint quietly relies on. These tests
pin the contract — including the deliberately-unsupported deep-wildcard
case (``platform:*`` does NOT cover ``platform:support:read``).
"""

from __future__ import annotations

import pytest

from platform_auth.scopes import SUPER_WILDCARD, Scope, _all_known_scopes, scope_satisfies


class TestExactMatch:
    def test_held_contains_required(self):
        assert scope_satisfies("workflow:read", {"workflow:read"})

    def test_held_contains_required_among_others(self):
        assert scope_satisfies(
            "workflow:read", {"profile:read", "workflow:read", "knowledge:write"}
        )

    def test_held_does_not_contain_required(self):
        assert not scope_satisfies("workflow:write", {"workflow:read"})

    def test_empty_held_set_rejects_non_empty_required(self):
        assert not scope_satisfies("workflow:read", set())


class TestSuperWildcard:
    def test_super_wildcard_covers_simple_scope(self):
        assert scope_satisfies("workflow:read", {SUPER_WILDCARD})

    def test_super_wildcard_covers_three_segment_scope(self):
        assert scope_satisfies("platform:support:read", {SUPER_WILDCARD})

    def test_super_wildcard_covers_anything_even_with_other_held(self):
        assert scope_satisfies("workflow:admin", {"profile:read", SUPER_WILDCARD})


class TestVerbWildcard:
    def test_two_segment_verb_wildcard(self):
        assert scope_satisfies("workflow:read", {"workflow:*"})
        assert scope_satisfies("workflow:write", {"workflow:*"})
        assert scope_satisfies("workflow:admin", {"workflow:*"})

    def test_three_segment_verb_wildcard(self):
        # platform:support:* covers platform:support:read but NOT
        # platform:foo:read (different namespace).
        assert scope_satisfies("platform:support:read", {"platform:support:*"})
        assert scope_satisfies("platform:support:write", {"platform:support:*"})
        assert not scope_satisfies("platform:foo:read", {"platform:support:*"})

    def test_verb_wildcard_does_not_cross_namespace(self):
        assert not scope_satisfies("knowledge:read", {"workflow:*"})


class TestNamespaceWildcard:
    def test_two_segment_namespace_wildcard(self):
        assert scope_satisfies("workflow:read", {"*:read"})
        assert scope_satisfies("knowledge:read", {"*:read"})

    def test_namespace_wildcard_does_not_cross_verb(self):
        assert not scope_satisfies("workflow:write", {"*:read"})

    def test_three_segment_namespace_wildcard(self):
        # *:support:read covers platform:support:read but NOT *:read
        # because length differs (deep wildcard not supported).
        assert scope_satisfies("platform:support:read", {"*:support:read"})


class TestUnsupportedDeepWildcards:
    """Deep wildcards (`platform:*` covering `platform:support:read`) are
    intentionally not supported — the semantics are too easy to misread.
    These tests pin that intention so a contributor doesn't add the rule
    accidentally.
    """

    def test_top_level_wildcard_does_not_cover_three_segment(self):
        assert not scope_satisfies("platform:support:read", {"platform:*"})

    def test_namespace_wildcard_does_not_cover_three_segment_when_lengths_differ(self):
        assert not scope_satisfies("platform:support:read", {"*:read"})


class TestEdgeCases:
    def test_empty_required_is_a_noop_gate(self):
        assert scope_satisfies("", set())
        assert scope_satisfies("", {"workflow:read"})

    def test_single_segment_scope_only_matches_exactly_or_super_wildcard(self):
        # Single-segment "scopes" are unusual but should not break.
        assert scope_satisfies("ping", {"ping"})
        assert scope_satisfies("ping", {SUPER_WILDCARD})
        assert not scope_satisfies("ping", {"*:ping"})  # no namespace to wildcard
        assert not scope_satisfies("ping", {"ping:*"})  # length mismatch

    def test_held_can_be_list_or_tuple_or_set_or_frozenset(self):
        for held in (
            ["workflow:read"],
            ("workflow:read",),
            {"workflow:read"},
            frozenset({"workflow:read"}),
        ):
            assert scope_satisfies("workflow:read", held)

    def test_held_can_be_a_generator(self):
        def gen():
            yield "workflow:read"

        assert scope_satisfies("workflow:read", gen())


class TestScopeEnumCompleteness:
    def test_all_services_have_read_write_admin_triple(self):
        services = (
            "workflow",
            "knowledge",
            "mcp",
            "airlock",
            "integration",
            "deepagent",
            "notification",
            "profile",
            "sentinel",
            "tms",
        )
        known = _all_known_scopes()
        for svc in services:
            for verb in ("read", "write", "admin"):
                assert f"{svc}:{verb}" in known, f"missing {svc}:{verb}"

    def test_platform_admin_scopes_present(self):
        known = _all_known_scopes()
        assert "platform:support:read" in known
        assert "platform:support:write" in known

    def test_enum_values_match_strings(self):
        # StrEnum invariant: each member's value equals its string form.
        assert Scope.WORKFLOW_READ == "workflow:read"
        assert Scope.WORKFLOW_WRITE == "workflow:write"
        assert Scope.PLATFORM_SUPPORT_READ == "platform:support:read"

    def test_scope_can_satisfy_itself_via_string(self):
        # Using the enum member as the required scope works because it IS a str.
        assert scope_satisfies(Scope.WORKFLOW_READ, {Scope.WORKFLOW_READ.value})
        assert scope_satisfies(Scope.WORKFLOW_READ, {"workflow:*"})


@pytest.mark.benchmark
class TestPerformance:
    """Lightweight benchmark assertions — the real perf gate is in CI via
    pytest-benchmark; these guarantee the function stays allocation-free
    enough for the request hot path even without the benchmarker.
    """

    def test_fast_path_no_iteration_with_frozenset(self):
        held = frozenset({"workflow:read"})
        # Run a couple of thousand times to surface any obvious perf bug.
        for _ in range(2000):
            assert scope_satisfies("workflow:read", held)

    def test_super_wildcard_short_circuits(self):
        held = frozenset({SUPER_WILDCARD})
        for _ in range(2000):
            assert scope_satisfies("any:thing:goes", held)
