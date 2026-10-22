"""UI kit declarations must match the files they describe.

A layout, component feature or fragment declares the Vue UI kits it renders
with (``forge.ui_kits``); the resolver refuses it for a project on another kit.
The declarations are only as good as the files behind them, so this lint reads
the files. Every Vue-shipping fragment (each component feature compiles to one)
that renders with ``nuxt-ui`` — by declaring it, or by declaring nothing, which
means any kit — must not import the shadcn kit or use its colour token classes,
which Nuxt UI does not define. Every declared kit must be a registered one.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from forge import layout_variants as lv
from forge import ui_kits
from forge.components import COMPONENT_REGISTRY
from forge.config import FrontendFramework
from forge.fragments import FRAGMENT_REGISTRY
from forge.fragments._spec import _resolve_fragment_dir

# Modules of the shadcn kit: the generated kit itself and the libraries it wraps.
_SHADCN_IMPORT = re.compile(
    r"""from\s+['"](@/shared/ui(?:/[^'"]*)?|radix-vue|@lucide/vue|vue-sonner)['"]"""
)
# Colour utilities backed by the shadcn tokens in the template's main.css. Nuxt UI
# names its own (text-muted, bg-default, ...); names both share are left out.
_SHADCN_CLASS = re.compile(
    r"\b(?:bg|text|border|ring|fill|stroke|outline|divide|placeholder|from|via|to)-"
    r"(?:background|foreground|card|card-foreground|popover|popover-foreground|"
    r"primary-foreground|secondary-foreground|muted-foreground|accent|accent-foreground|"
    r"destructive|destructive-foreground|input|sidebar(?:-[a-z]+)*)(?![\w-])"
)


def _vue_fragments() -> dict[str, list[Path]]:
    """Fragment name → its ``files/`` trees, for every fragment shipping ``.vue`` files."""
    found: dict[str, list[Path]] = {}
    for name, fragment in FRAGMENT_REGISTRY.items():
        trees = [
            _resolve_fragment_dir(impl.fragment_dir) / "files"
            for impl in fragment.implementations.values()
        ]
        trees = [tree for tree in trees if tree.is_dir() and any(tree.rglob("*.vue"))]
        if trees:
            found[name] = trees
    return found


def _kits(fragment_name: str) -> tuple[str, ...]:
    declared = FRAGMENT_REGISTRY[fragment_name].ui_kits
    return declared or tuple(ui_kits.UI_KITS)


def _shadcn_dependencies(trees: list[Path]) -> list[str]:
    hits = []
    for tree in trees:
        for path in sorted(tree.rglob("*")):
            if path.suffix not in {".vue", ".ts"}:
                continue
            text = path.read_text(encoding="utf-8")
            rel = path.relative_to(tree).as_posix()
            hits += [f"{rel}: imports {m}" for m in sorted(set(_SHADCN_IMPORT.findall(text)))]
            hits += [f"{rel}: class {m}" for m in sorted(set(_SHADCN_CLASS.findall(text)))]
    return hits


def test_the_lint_sees_the_vue_fragments() -> None:
    # Guard against a lint that silently checks nothing.
    names = set(_vue_fragments())
    assert {"platform_auth_session_timeout_vue", "mcp_ui", "component_Checkbox"} <= names
    assert len(names) >= 15


@pytest.mark.parametrize("fragment_name", sorted(_vue_fragments()))
def test_fragments_rendering_with_nuxt_ui_do_not_depend_on_shadcn(fragment_name: str) -> None:
    if "nuxt-ui" not in _kits(fragment_name):
        pytest.skip("declares the shadcn kit only")
    assert _shadcn_dependencies(_vue_fragments()[fragment_name]) == [], (
        f"{fragment_name} renders with nuxt-ui (declared, or no ui_kits = any kit) "
        "but depends on the shadcn kit; declare ui_kits = ('shadcn',) or remove the dependency"
    )


def test_the_shadcn_markers_catch_a_shadcn_tree() -> None:
    # The Checkbox component is built on radix-vue and the kit's tokens.
    assert _shadcn_dependencies(_vue_fragments()["component_Checkbox"])


def test_declared_kits_are_registered() -> None:
    registered = set(ui_kits.UI_KITS)
    declared: dict[str, tuple[str, ...]] = {}
    for name, fragment in FRAGMENT_REGISTRY.items():
        declared[f"fragment {name}"] = fragment.ui_kits
    for name, node in COMPONENT_REGISTRY.items():
        declared[f"component {name}"] = node.ui_kits
        declared[f"component {name} replaced_by"] = tuple(node.replaced_by)
    for name in lv.available_layouts(FrontendFramework.VUE):
        variant = lv.get_layout_variant(FrontendFramework.VUE, name)
        assert variant is not None
        declared[f"layout vue/{name}"] = variant.ui_kits
    unknown = {owner: kits for owner, kits in declared.items() if set(kits) - registered}
    assert unknown == {}
