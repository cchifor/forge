"""Tests for compiling a component into the existing fragment graph (Phase 3).

A component's emitter compiles to a *project-scoped*, frontend-targeted
``Fragment`` — the exact shape ``features/auth`` and ``features/platform`` use
to ship ``.vue`` files (registered against ``BackendLanguage.PYTHON`` only to
satisfy the non-empty implementations map, ``scope="project"``,
``target_frontends=(...)``). This is the bridge from the component tier down to
the option/fragment graph the generator already applies.
"""

from __future__ import annotations

from pathlib import Path

from forge.components import ComponentNode, component_fragment_name, component_fragments
from forge.config import BackendLanguage, FrontendFramework


def test_compiles_to_project_scoped_vue_fragment(tmp_path: Path) -> None:
    node = ComponentNode(name="EntityList", layer=1, contract="EntityContract")
    frags = component_fragments(node, templates_root=tmp_path)
    assert len(frags) == 1
    frag = frags[0]
    assert frag.name == "component_EntityList"
    assert frag.target_frontends == (FrontendFramework.VUE,)
    impl = frag.implementations[BackendLanguage.PYTHON]
    assert impl.scope == "project"
    assert "EntityList" in impl.fragment_dir


def test_children_become_fragment_dependencies(tmp_path: Path) -> None:
    node = ComponentNode(
        name="Panel", layer=2, children={"FilterBar": "*", "DataTable": "^1.0"}
    )
    frag = component_fragments(node, templates_root=tmp_path)[0]
    assert set(frag.depends_on) == {"component_FilterBar", "component_DataTable"}


def test_fragment_name_helper() -> None:
    assert component_fragment_name("DataTable") == "component_DataTable"


def test_layer1_pure_ui_has_no_dependencies(tmp_path: Path) -> None:
    node = ComponentNode(name="Spacer", layer=1)
    frag = component_fragments(node, templates_root=tmp_path)[0]
    assert frag.depends_on == ()
    assert frag.target_frontends == (FrontendFramework.VUE,)
    # RFC-011 opt-out: Vue-first, so a skip reason is declared.
    assert frag.frontend_skip_reason


def test_svelte_target_is_selectable(tmp_path: Path) -> None:
    node = ComponentNode(name="Card", layer=1)
    frag = component_fragments(
        node, frontend=FrontendFramework.SVELTE, templates_root=tmp_path
    )[0]
    assert frag.target_frontends == (FrontendFramework.SVELTE,)
