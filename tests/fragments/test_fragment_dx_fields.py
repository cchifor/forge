"""Tests for the Fragment-DX wave: ``shared_env_vars``, ``before``, ``after``.

These cheap-wins land on the ``Fragment`` dataclass to reduce friction
authoring multi-language fragments:

- ``shared_env_vars`` lets a fragment declare backend-agnostic env vars
  once instead of repeating them per :class:`FragmentImplSpec.env_vars`.
- ``before`` / ``after`` give fragments a soft-ordering hook that
  doesn't pull the neighbour into the plan (unlike ``depends_on``).

Coverage focus:
1. The merge-precedence rule (per-impl wins on key collision).
2. The empty-tuple default (no behaviour change for the 74 existing
   fragments that don't opt in).
3. before/after edges flow through the resolver's toposort.
4. Cycles created by before/after are caught by registry audit.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from forge.appliers.plan import FragmentPlan, _merge_env_vars
from forge.capability_resolver import _topo_sort
from forge.config import BackendLanguage
from forge.errors import FragmentError
from forge.fragments._registry import _FragmentRegistry
from forge.fragments._spec import Fragment, FragmentImplSpec

# ---------------------------------------------------------------------------
# shared_env_vars
# ---------------------------------------------------------------------------


def test_shared_env_vars_field_default_is_empty():
    frag = Fragment(name="x", implementations={})
    assert frag.shared_env_vars == ()


def test_merge_env_vars_shared_only():
    merged = _merge_env_vars(
        (("AWS_REGION", "us-east-1"), ("S3_ENDPOINT_URL", "http://s3:9000")),
        (),
    )
    assert merged == (("AWS_REGION", "us-east-1"), ("S3_ENDPOINT_URL", "http://s3:9000"))


def test_merge_env_vars_per_impl_only():
    merged = _merge_env_vars((), (("PG_HOST", "postgres"),))
    assert merged == (("PG_HOST", "postgres"),)


def test_merge_env_vars_shared_first_then_per_impl():
    """Shared comes first; per-impl tail-appends."""
    merged = _merge_env_vars(
        (("AWS_REGION", "us-east-1"),),
        (("PG_HOST", "postgres"),),
    )
    assert merged == (
        ("AWS_REGION", "us-east-1"),
        ("PG_HOST", "postgres"),
    )


def test_merge_env_vars_per_impl_overrides_shared_on_collision():
    """A per-impl entry with the same key as a shared entry wins."""
    merged = _merge_env_vars(
        (("AWS_REGION", "us-east-1"), ("AWS_PROFILE", "default")),
        (("AWS_REGION", "eu-west-1"),),
    )
    # AWS_REGION from per-impl overrides shared; AWS_PROFILE from shared survives.
    assert merged == (
        ("AWS_PROFILE", "default"),
        ("AWS_REGION", "eu-west-1"),
    )


def test_from_impl_uses_shared_env_vars(tmp_path: Path):
    """End-to-end: a fragment with shared_env_vars + per-impl env_vars
    surfaces the merged tuple on the resulting :class:`FragmentPlan`.
    """
    frag_dir = tmp_path / "my_frag"
    frag_dir.mkdir()
    impl = FragmentImplSpec(
        fragment_dir=str(frag_dir),
        env_vars=(("DATABASE_URL", "postgres://x"),),
    )
    fp = FragmentPlan.from_impl(
        impl,
        feature_key="my_frag",
        shared_env_vars=(
            ("AWS_REGION", "us-east-1"),
            ("S3_ENDPOINT_URL", "http://s3:9000"),
        ),
    )
    assert fp.env_vars == (
        ("AWS_REGION", "us-east-1"),
        ("S3_ENDPOINT_URL", "http://s3:9000"),
        ("DATABASE_URL", "postgres://x"),
    )


def test_from_impl_default_shared_env_vars_is_empty(tmp_path: Path):
    """Existing callers (no shared_env_vars kwarg) see no behaviour change."""
    frag_dir = tmp_path / "my_frag"
    frag_dir.mkdir()
    impl = FragmentImplSpec(
        fragment_dir=str(frag_dir),
        env_vars=(("PG_HOST", "postgres"),),
    )
    fp = FragmentPlan.from_impl(impl, feature_key="my_frag")
    assert fp.env_vars == (("PG_HOST", "postgres"),)


# ---------------------------------------------------------------------------
# before / after
# ---------------------------------------------------------------------------


def _basic_impl(name: str, tmp_path: Path) -> FragmentImplSpec:
    d = tmp_path / name
    d.mkdir(parents=True, exist_ok=True)
    return FragmentImplSpec(fragment_dir=str(d))


def _seed_registry(monkeypatch: pytest.MonkeyPatch, frags: list[Fragment]) -> None:
    """Replace FRAGMENT_REGISTRY with a fresh _FragmentRegistry seeded with frags.

    Mirrors the pattern used elsewhere in the test suite — see
    ``tests/test_capability_resolver.py::isolated_registries``.
    """
    fake = _FragmentRegistry()
    for f in frags:
        fake[f.name] = f
    monkeypatch.setattr("forge.capability_resolver.FRAGMENT_REGISTRY", fake)
    monkeypatch.setattr("forge.fragments._registry.FRAGMENT_REGISTRY", fake)


def test_after_field_default_is_empty():
    frag = Fragment(name="x", implementations={})
    assert frag.after == ()
    assert frag.before == ()


def test_after_constrains_topo_sort(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """``after=("X",)`` makes self land after X when both are in the plan."""
    a = Fragment(
        name="a",
        implementations={BackendLanguage.PYTHON: _basic_impl("a", tmp_path)},
        after=("b",),
    )
    b = Fragment(
        name="b",
        implementations={BackendLanguage.PYTHON: _basic_impl("b", tmp_path)},
    )
    _seed_registry(monkeypatch, [a, b])
    order = _topo_sort({"a", "b"})
    assert order == ["b", "a"], f"a should follow b via after-edge; got {order}"


def test_before_constrains_topo_sort(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """``before=("Y",)`` makes self land before Y when both are in the plan."""
    a = Fragment(
        name="a",
        implementations={BackendLanguage.PYTHON: _basic_impl("a", tmp_path)},
        before=("b",),
    )
    b = Fragment(
        name="b",
        implementations={BackendLanguage.PYTHON: _basic_impl("b", tmp_path)},
    )
    _seed_registry(monkeypatch, [a, b])
    order = _topo_sort({"a", "b"})
    assert order == ["a", "b"], f"a should precede b via before-edge; got {order}"


def test_after_is_soft_inert_when_target_absent(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """``after`` only constrains when the target is in the plan."""
    a = Fragment(
        name="a",
        implementations={BackendLanguage.PYTHON: _basic_impl("a", tmp_path)},
        after=("missing",),  # 'missing' is NOT in the plan
    )
    _seed_registry(monkeypatch, [a])
    order = _topo_sort({"a"})
    assert order == ["a"]


def test_before_is_soft_inert_when_target_absent(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """``before`` only constrains when the target is in the plan."""
    a = Fragment(
        name="a",
        implementations={BackendLanguage.PYTHON: _basic_impl("a", tmp_path)},
        before=("missing",),  # 'missing' is NOT in the plan
    )
    _seed_registry(monkeypatch, [a])
    order = _topo_sort({"a"})
    assert order == ["a"]


def test_topo_sort_uses_order_as_tiebreak_when_no_before_after(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    """Numeric ``order`` still tiebreaks within a ready set."""
    high = Fragment(
        name="high",
        implementations={BackendLanguage.PYTHON: _basic_impl("high", tmp_path)},
        order=200,
    )
    low = Fragment(
        name="low",
        implementations={BackendLanguage.PYTHON: _basic_impl("low", tmp_path)},
        order=10,
    )
    _seed_registry(monkeypatch, [high, low])
    order = _topo_sort({"high", "low"})
    assert order == ["low", "high"]


def test_before_after_cycle_detected_at_registry_freeze(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    """A before/after cycle in the full registry is caught at freeze time."""
    fake = _FragmentRegistry()
    fake["a"] = Fragment(
        name="a",
        implementations={BackendLanguage.PYTHON: _basic_impl("a", tmp_path)},
        before=("b",),
    )
    fake["b"] = Fragment(
        name="b",
        implementations={BackendLanguage.PYTHON: _basic_impl("b", tmp_path)},
        before=("a",),  # cycle: a before b, b before a
    )
    with pytest.raises(FragmentError) as exc:
        fake.freeze()
    msg = str(exc.value)
    assert "Cyclic dependencies detected" in msg
    # The DFS should surface the actual cycle in the error context.
    assert exc.value.context.get("cycle_path"), exc.value.context


def test_before_after_cycle_via_mixed_edges(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Cycle composed of one depends_on + one before edge is still caught."""
    fake = _FragmentRegistry()
    fake["a"] = Fragment(
        name="a",
        implementations={BackendLanguage.PYTHON: _basic_impl("a", tmp_path)},
        depends_on=("b",),  # a after b
    )
    fake["b"] = Fragment(
        name="b",
        implementations={BackendLanguage.PYTHON: _basic_impl("b", tmp_path)},
        after=("a",),  # b after a → cycle
    )
    with pytest.raises(FragmentError):
        fake.freeze()


def test_before_after_chain_orders_correctly(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Three-fragment chain with mixed before/after produces a single valid order."""
    a = Fragment(
        name="a",
        implementations={BackendLanguage.PYTHON: _basic_impl("a", tmp_path)},
        before=("b",),  # a before b
    )
    b = Fragment(
        name="b",
        implementations={BackendLanguage.PYTHON: _basic_impl("b", tmp_path)},
        after=("a",),  # redundant with a.before — still valid
    )
    c = Fragment(
        name="c",
        implementations={BackendLanguage.PYTHON: _basic_impl("c", tmp_path)},
        after=("b",),  # c after b → c last
    )
    _seed_registry(monkeypatch, [a, b, c])
    order = _topo_sort({"a", "b", "c"})
    assert order == ["a", "b", "c"]


# ---------------------------------------------------------------------------
# Codex Phase B round 1 — validation + duplicate-key tests
# ---------------------------------------------------------------------------


def test_fragment_rejects_self_in_before():
    """``__post_init__`` mirrors the existing conflicts_with self-ref check."""
    with pytest.raises(FragmentError, match="lists itself in before"):
        Fragment(name="a", implementations={}, before=("a",))


def test_fragment_rejects_self_in_after():
    with pytest.raises(FragmentError, match="lists itself in after"):
        Fragment(name="a", implementations={}, after=("a",))


def test_fragment_rejects_overlap_in_before_and_after():
    """Logically impossible: can't apply both before AND after the same neighbour."""
    with pytest.raises(FragmentError, match="both before and"):
        Fragment(name="a", implementations={}, before=("b",), after=("b",))


def test_merge_env_vars_preserves_duplicate_keys_within_shared():
    """Document the current behaviour: duplicates within shared survive verbatim.

    Most ``.env`` parsers (dotenv, docker-compose) use last-wins; the
    merge function doesn't dedupe to keep this contract explicit. If a
    future consumer rejects duplicates, the author needs to dedupe at
    the Fragment-construction site rather than rely on the merge
    function.
    """
    merged = _merge_env_vars(
        (("A", "1"), ("A", "2"), ("B", "x")),
        (),
    )
    assert merged == (("A", "1"), ("A", "2"), ("B", "x"))
