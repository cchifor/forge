"""Integration tests for the frontend-layouts two-stage render.

Complements the unit tests in ``test_layout_variants.py`` (registry/config) and
the manifest round-trip tests by exercising the FULL Copier render path:
generate a project per layout and assert the two-stage overlay produced a
coherent tree (the layout's own region components land, its MainLayout renders
with no leftover Jinja) and that chat-off generation degrades cleanly. Codex
flagged this path as the one gap the unit tests didn't cover.

Uses ``dry_run=True`` so rendering happens without the post-generate npm tasks
(same approach as ``test_golden_snapshots``).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from forge.config import (
    BackendConfig,
    BackendLanguage,
    FrontendConfig,
    FrontendFramework,
    ProjectConfig,
)
from forge.generator import generate


def _generate(tmp_path: Path, layout: str, *, include_chat: bool = True) -> Path:
    """Generate a Vue project with ``layout`` and return its project root."""
    cfg = ProjectConfig(
        project_name="lt",
        output_dir=str(tmp_path),
        backends=[
            BackendConfig(
                name="api",
                project_name="lt",
                language=BackendLanguage.PYTHON,
                features=["items"],
            )
        ],
        frontend=FrontendConfig(
            project_name="lt",
            framework=FrontendFramework.VUE,
            layout=layout,
            include_chat=include_chat,
            include_openapi=True,
        ),
    )
    return Path(generate(cfg, quiet=True, dry_run=True))


def _main_layout(root: Path) -> Path:
    return root / "apps" / "frontend" / "src" / "shared" / "layouts" / "MainLayout.vue"


# The signature region component each non-sidebar overlay must emit.
_OVERLAY_COMPONENTS = {
    "topnav": "TopNavBar.vue",
    "tabbar": "BottomTabBar.vue",
    "threepane": "RightPanel.vue",
    "bento": "BentoGrid.vue",
    "docs": "DocTreeNav.vue",
}


@pytest.mark.parametrize("layout,component", sorted(_OVERLAY_COMPONENTS.items()))
def test_two_stage_overlay_emits_region(tmp_path: Path, layout: str, component: str) -> None:
    """The overlay's signature region component lands in the rendered tree."""
    root = _generate(tmp_path, layout)
    frontend = root / "apps" / "frontend"
    assert list(frontend.rglob(component)), (
        f"{layout}: overlay region {component} not in rendered tree (overlay didn't apply?)"
    )
    ml = _main_layout(root)
    assert ml.is_file(), f"{layout}: MainLayout.vue not rendered"
    assert "{%" not in ml.read_text(encoding="utf-8"), (
        f"{layout}: unresolved Jinja tag in rendered MainLayout"
    )


def test_sidebar_is_self_contained_base(tmp_path: Path) -> None:
    """The default sidebar layout renders the base shell (AppSidebar)."""
    ml = _main_layout(_generate(tmp_path, "sidebar"))
    assert ml.is_file()
    assert "AppSidebar" in ml.read_text(encoding="utf-8")


@pytest.mark.parametrize("layout", sorted(_OVERLAY_COMPONENTS))
def test_chat_off_degrades_cleanly(tmp_path: Path, layout: str) -> None:
    """Each layout renders with chat disabled, leaving no unresolved Jinja or
    a dangling AI chat panel in the shell."""
    ml = _main_layout(_generate(tmp_path, layout, include_chat=False))
    assert ml.is_file(), f"{layout}: MainLayout.vue not rendered (chat off)"
    txt = ml.read_text(encoding="utf-8")
    assert "{%" not in txt, f"{layout}: unresolved Jinja tag in chat-off MainLayout"
    assert "<AiChat" not in txt, f"{layout}: chat-off MainLayout still mounts <AiChat>"
