"""Invariants for the ``AsyncStateBlock`` Layer-1 component feature.

Auto-discovered as a selectable component (like StatCard / EntityList), so it
ships only when chosen — no golden snapshot includes it by default. Ships two
sibling Vue components: the async-state orchestrator and the FeatureEmptyState
it renders for the empty/error branches.
"""

from __future__ import annotations

from pathlib import Path

from forge.components._registry import COMPONENT_REGISTRY
from forge.fragments import FRAGMENT_REGISTRY


def test_component_autoregistered() -> None:
    assert "AsyncStateBlock" in COMPONENT_REGISTRY
    assert "component_AsyncStateBlock" in FRAGMENT_REGISTRY


def test_emitter_ships_both_vue_components() -> None:
    frag = FRAGMENT_REGISTRY["component_AsyncStateBlock"]
    assert frag.implementations, "emitter fragment has no implementations"
    impl = next(iter(frag.implementations.values()))
    base = Path(impl.fragment_dir) / "files" / "src" / "shared" / "components"
    assert (base / "AsyncStateBlock.vue").is_file()
    assert (base / "FeatureEmptyState.vue").is_file()

    orchestrator = (base / "AsyncStateBlock.vue").read_text(encoding="utf-8")
    # Renders the bundled empty-state and orchestrates the full ladder.
    assert "FeatureEmptyState" in orchestrator
    assert "loading -> error -> empty -> success" in orchestrator
    # Uses only deps the Vue template already ships (lucide icons + ui/button).
    empty = (base / "FeatureEmptyState.vue").read_text(encoding="utf-8")
    assert "@/shared/ui/button" in empty
