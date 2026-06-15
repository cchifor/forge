"""may_act policy tests."""

from __future__ import annotations

from platform_auth.may_act import (
    AllowAllMayActPolicy,
    MayActPolicy,
    StaticMayActPolicy,
)


class TestStaticMayActPolicy:
    def test_authorized_actor_for_audience(self):
        policy = StaticMayActPolicy({"svc-knowledge": ["svc-deepagent", "svc-workflow"]})
        assert policy.is_authorized("svc-deepagent", "svc-knowledge")
        assert policy.is_authorized("svc-workflow", "svc-knowledge")

    def test_unauthorized_actor_for_audience(self):
        policy = StaticMayActPolicy({"svc-knowledge": ["svc-deepagent"]})
        assert not policy.is_authorized("svc-sentinel", "svc-knowledge")

    def test_unknown_audience_denies_everyone(self):
        policy = StaticMayActPolicy({"svc-knowledge": ["svc-deepagent"]})
        assert not policy.is_authorized("svc-deepagent", "svc-unknown")

    def test_empty_actor_denies(self):
        policy = StaticMayActPolicy({"svc-knowledge": ["svc-deepagent"]})
        assert not policy.is_authorized("", "svc-knowledge")

    def test_empty_audience_denies(self):
        policy = StaticMayActPolicy({"svc-knowledge": ["svc-deepagent"]})
        assert not policy.is_authorized("svc-deepagent", "")

    def test_default_construction_denies_everything(self):
        # Safe default: no allowlist → no impersonation possible.
        policy = StaticMayActPolicy()
        assert not policy.is_authorized("svc-deepagent", "svc-knowledge")

    def test_replace_swaps_policy_atomically(self):
        policy = StaticMayActPolicy({"svc-knowledge": ["svc-old"]})
        assert policy.is_authorized("svc-old", "svc-knowledge")
        policy.replace({"svc-knowledge": ["svc-new"]})
        assert not policy.is_authorized("svc-old", "svc-knowledge")
        assert policy.is_authorized("svc-new", "svc-knowledge")

    def test_authorized_actors_for_returns_frozenset(self):
        policy = StaticMayActPolicy({"svc-knowledge": ["svc-a", "svc-b"]})
        actors = policy.authorized_actors_for("svc-knowledge")
        assert actors == frozenset({"svc-a", "svc-b"})
        assert isinstance(actors, frozenset)

    def test_authorized_actors_for_unknown_audience_is_empty(self):
        policy = StaticMayActPolicy()
        assert policy.authorized_actors_for("svc-x") == frozenset()

    def test_implements_protocol(self):
        policy = StaticMayActPolicy()
        assert isinstance(policy, MayActPolicy)


class TestAllowAllMayActPolicy:
    def test_permits_any_combination(self):
        policy = AllowAllMayActPolicy()
        assert policy.is_authorized("svc-anything", "svc-any-audience")
        assert policy.is_authorized("svc-x", "svc-y")

    def test_still_rejects_empty_actor(self):
        policy = AllowAllMayActPolicy()
        assert not policy.is_authorized("", "svc-y")

    def test_still_rejects_empty_audience(self):
        policy = AllowAllMayActPolicy()
        assert not policy.is_authorized("svc-x", "")

    def test_implements_protocol(self):
        policy = AllowAllMayActPolicy()
        assert isinstance(policy, MayActPolicy)
