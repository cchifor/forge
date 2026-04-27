"""Tests for Epic I's ``_FragmentRegistry`` freeze + audit.

Every test operates on a fresh ``_FragmentRegistry`` instance rather
than mutating the real ``FRAGMENT_REGISTRY`` — that way the real
built-in audit is unaffected by test setup, and parallel pytest-xdist
workers don't race each other.
"""

from __future__ import annotations

import logging

import pytest

from forge.config import BackendLanguage
from forge.errors import (
    PLUGIN_COLLISION,
    PLUGIN_REGISTRY_FROZEN,
    FragmentError,
    PluginError,
)
from forge.fragments import (
    Fragment,
    FragmentImplSpec,
    _FragmentRegistry,
    register_fragment,
)


def _mk(
    name: str,
    *,
    depends_on: tuple[str, ...] = (),
    conflicts_with: tuple[str, ...] = (),
) -> Fragment:
    """Helper — minimal Fragment with one Python implementation."""
    return Fragment(
        name=name,
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(fragment_dir=f"{name}/python")
        },
        depends_on=depends_on,
        conflicts_with=conflicts_with,
    )


# ---------------------------------------------------------------------------
# Fragment.__post_init__ self-validation
# ---------------------------------------------------------------------------


def test_fragment_rejects_self_conflict() -> None:
    with pytest.raises(FragmentError, match="lists itself"):
        _mk("foo", conflicts_with=("foo",))


def test_fragment_rejects_depends_conflict_overlap() -> None:
    with pytest.raises(FragmentError, match="depends_on and conflicts_with"):
        _mk("foo", depends_on=("bar",), conflicts_with=("bar",))


def test_fragment_with_disjoint_depends_and_conflicts_is_fine() -> None:
    frag = _mk("foo", depends_on=("bar",), conflicts_with=("baz",))
    assert frag.depends_on == ("bar",)
    assert frag.conflicts_with == ("baz",)


# ---------------------------------------------------------------------------
# _FragmentRegistry freeze semantics
# ---------------------------------------------------------------------------


def test_registry_accepts_mutation_before_freeze() -> None:
    reg = _FragmentRegistry()
    reg["a"] = _mk("a")
    assert "a" in reg
    assert not reg.frozen


def test_registry_freeze_locks_setitem() -> None:
    reg = _FragmentRegistry()
    reg["a"] = _mk("a")
    reg.freeze()
    assert reg.frozen
    with pytest.raises(PluginError) as excinfo:
        reg["b"] = _mk("b")
    assert excinfo.value.code == PLUGIN_REGISTRY_FROZEN
    assert "b" in excinfo.value.context.get("fragment", "")


def test_registry_freeze_locks_delitem() -> None:
    reg = _FragmentRegistry()
    reg["a"] = _mk("a")
    reg.freeze()
    with pytest.raises(PluginError) as excinfo:
        del reg["a"]
    assert excinfo.value.code == PLUGIN_REGISTRY_FROZEN


def test_registry_reset_for_tests_thaws() -> None:
    reg = _FragmentRegistry()
    reg["a"] = _mk("a")
    reg.freeze()
    reg._reset_for_tests()
    assert not reg.frozen
    assert "a" not in reg
    # And the reset registry accepts new registrations again.
    reg["b"] = _mk("b")
    assert "b" in reg


# ---------------------------------------------------------------------------
# Audit: orphan depends_on
# ---------------------------------------------------------------------------


def test_audit_flags_orphan_depends_on() -> None:
    reg = _FragmentRegistry()
    reg["a"] = _mk("a", depends_on=("nonexistent_fragment",))
    with pytest.raises(FragmentError) as excinfo:
        reg.freeze()
    assert "depends_on unknown fragment" in excinfo.value.message
    assert excinfo.value.context["missing"] == ["nonexistent_fragment"]
    # Freezing failed, so the registry is still mutable.
    assert not reg.frozen


def test_audit_accepts_resolved_depends_on() -> None:
    reg = _FragmentRegistry()
    reg["a"] = _mk("a", depends_on=("b",))
    reg["b"] = _mk("b")
    reg.freeze()
    assert reg.frozen


# ---------------------------------------------------------------------------
# Audit: orphan conflicts_with (warns, doesn't raise)
# ---------------------------------------------------------------------------


def test_orphan_conflicts_with_warns_not_raises(caplog: pytest.LogCaptureFixture) -> None:
    reg = _FragmentRegistry()
    reg["a"] = _mk("a", conflicts_with=("ghost",))
    with caplog.at_level(logging.WARNING, logger="forge.fragments"):
        reg.freeze()
    assert reg.frozen
    assert any("ghost" in rec.getMessage() for rec in caplog.records)


# ---------------------------------------------------------------------------
# Audit: conflict symmetry (warns on asymmetric declarations)
# ---------------------------------------------------------------------------


def test_asymmetric_conflicts_warns(caplog: pytest.LogCaptureFixture) -> None:
    reg = _FragmentRegistry()
    reg["a"] = _mk("a", conflicts_with=("b",))
    reg["b"] = _mk("b")  # b doesn't declare conflict with a
    with caplog.at_level(logging.WARNING, logger="forge.fragments"):
        reg.freeze()
    assert reg.frozen
    warnings = [rec.getMessage() for rec in caplog.records if rec.levelno == logging.WARNING]
    assert any("'a' declares conflict with 'b'" in w for w in warnings)


def test_symmetric_conflicts_silent(caplog: pytest.LogCaptureFixture) -> None:
    reg = _FragmentRegistry()
    reg["a"] = _mk("a", conflicts_with=("b",))
    reg["b"] = _mk("b", conflicts_with=("a",))
    with caplog.at_level(logging.WARNING, logger="forge.fragments"):
        reg.freeze()
    # No symmetry complaint when both sides agree.
    symmetry_warnings = [
        rec.getMessage()
        for rec in caplog.records
        if rec.levelno == logging.WARNING and "declares conflict with" in rec.getMessage()
    ]
    assert symmetry_warnings == []


# ---------------------------------------------------------------------------
# Audit: cycle detection via toposort dry-run
# ---------------------------------------------------------------------------


def test_audit_detects_two_node_cycle() -> None:
    reg = _FragmentRegistry()
    reg["a"] = _mk("a", depends_on=("b",))
    reg["b"] = _mk("b", depends_on=("a",))
    with pytest.raises(FragmentError, match="Cyclic dependencies"):
        reg.freeze()


def test_audit_detects_three_node_cycle() -> None:
    reg = _FragmentRegistry()
    reg["a"] = _mk("a", depends_on=("b",))
    reg["b"] = _mk("b", depends_on=("c",))
    reg["c"] = _mk("c", depends_on=("a",))
    with pytest.raises(FragmentError) as excinfo:
        reg.freeze()
    assert "a" in excinfo.value.context["cycle_among"]
    assert "b" in excinfo.value.context["cycle_among"]
    assert "c" in excinfo.value.context["cycle_among"]


def test_audit_accepts_dag_with_shared_dep() -> None:
    reg = _FragmentRegistry()
    reg["leaf"] = _mk("leaf")
    reg["a"] = _mk("a", depends_on=("leaf",))
    reg["b"] = _mk("b", depends_on=("leaf",))
    reg["root"] = _mk("root", depends_on=("a", "b"))
    reg.freeze()
    assert reg.frozen


# ---------------------------------------------------------------------------
# Cycle path diagnostics (P2)
# ---------------------------------------------------------------------------


def test_cycle_error_surfaces_concrete_path_two_node() -> None:
    """Two-node cycle: error should show ``a → b → a`` so the author
    can see exactly which edge to delete."""
    reg = _FragmentRegistry()
    reg["a"] = _mk("a", depends_on=("b",))
    reg["b"] = _mk("b", depends_on=("a",))
    with pytest.raises(FragmentError) as excinfo:
        reg.freeze()
    msg = excinfo.value.message
    # Path is one of the two equivalent rotations.
    assert "a → b → a" in msg or "b → a → b" in msg
    cycle_path = excinfo.value.context.get("cycle_path", [])
    assert len(cycle_path) >= 3  # closing repetition included


def test_cycle_error_surfaces_concrete_path_three_node() -> None:
    """Three-node cycle path is fully reported, not just the unordered set."""
    reg = _FragmentRegistry()
    reg["a"] = _mk("a", depends_on=("b",))
    reg["b"] = _mk("b", depends_on=("c",))
    reg["c"] = _mk("c", depends_on=("a",))
    with pytest.raises(FragmentError) as excinfo:
        reg.freeze()
    cycle_path = excinfo.value.context.get("cycle_path", [])
    # The cycle is one of the three rotations a→b→c→a, b→c→a→b, c→a→b→c.
    # Whatever DFS picks, the closing element matches the opening.
    assert len(cycle_path) == 4
    assert cycle_path[0] == cycle_path[-1]
    # Every node appears exactly once in the body of the cycle.
    body = cycle_path[:-1]
    assert sorted(body) == ["a", "b", "c"]


def test_cycle_error_keeps_legacy_cycle_among_field() -> None:
    """The pre-P2 ``cycle_among`` context field stays populated so any
    consumers that branch on it keep working alongside the new ``cycle_path``."""
    reg = _FragmentRegistry()
    reg["a"] = _mk("a", depends_on=("b",))
    reg["b"] = _mk("b", depends_on=("a",))
    with pytest.raises(FragmentError) as excinfo:
        reg.freeze()
    assert "cycle_among" in excinfo.value.context
    assert sorted(excinfo.value.context["cycle_among"]) == ["a", "b"]


def test_cycle_path_isolates_cycle_when_dag_neighbours_present() -> None:
    """A small cycle inside a larger DAG: the path reports only the
    nodes actually in the cycle, not the unrelated DAG members."""
    reg = _FragmentRegistry()
    reg["leaf"] = _mk("leaf")
    reg["a"] = _mk("a", depends_on=("b", "leaf"))
    reg["b"] = _mk("b", depends_on=("a",))  # cycle a ↔ b
    reg["clean"] = _mk("clean", depends_on=("leaf",))
    with pytest.raises(FragmentError) as excinfo:
        reg.freeze()
    cycle_path = excinfo.value.context.get("cycle_path", [])
    # Cycle should only mention a + b (closing repetition included).
    assert set(cycle_path) == {"a", "b"}
    # ``leaf`` and ``clean`` aren't in the cycle.
    assert "leaf" not in cycle_path
    assert "clean" not in cycle_path


# ---------------------------------------------------------------------------
# register_fragment collision
# ---------------------------------------------------------------------------


def test_register_fragment_rejects_duplicate(monkeypatch: pytest.MonkeyPatch) -> None:
    # Swap in an isolated registry so we don't pollute the real one.
    # Post-Epic-1 split, ``register_fragment`` lives in
    # ``forge.fragments._registry`` and refers to the module-local
    # ``FRAGMENT_REGISTRY``; patching the package-level re-export
    # alone leaves the canonical reference unchanged. Patch both
    # locations so ``register_fragment`` sees the fake.
    fake = _FragmentRegistry()
    monkeypatch.setattr("forge.fragments._registry.FRAGMENT_REGISTRY", fake)
    monkeypatch.setattr("forge.fragments.FRAGMENT_REGISTRY", fake)
    register_fragment(_mk("unique_name"))
    with pytest.raises(PluginError) as excinfo:
        register_fragment(_mk("unique_name"))
    assert excinfo.value.code == PLUGIN_COLLISION


# ---------------------------------------------------------------------------
# Real built-in registry sanity
# ---------------------------------------------------------------------------


def test_real_registry_audit_passes() -> None:
    """The shipped FRAGMENT_REGISTRY must itself pass the audit.

    A failure here would mean a built-in fragment has an orphan
    depends_on or is in a cycle — a release-blocking bug in the
    fragment graph, which is exactly why Epic I landed.
    """
    from forge.fragments import FRAGMENT_REGISTRY

    # Thaw if a prior test in the same process froze it.
    was_frozen = FRAGMENT_REGISTRY.frozen
    FRAGMENT_REGISTRY.frozen = False
    try:
        FRAGMENT_REGISTRY._audit()  # private; we want the audit without toggling frozen
    finally:
        FRAGMENT_REGISTRY.frozen = was_frozen
