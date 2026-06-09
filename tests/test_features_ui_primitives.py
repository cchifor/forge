"""Invariants for the atomic UI primitive component features.

Three opt-in Layer-1 Vue primitives (selected via ``ProjectConfig.components``),
so each is absent from every golden preset and emits its self-contained file(s)
under ``src/shared/ui/<name>/`` only when selected:

- ``Switch`` — radix-vue toggle (``shared/ui/switch/``)
- ``StatusDot`` — colored status indicator dot (``shared/ui/status-dot/``)
- ``PageActionGroup`` — page action toolbar with overflow (``shared/ui/page-actions/``)
"""

from __future__ import annotations

from pathlib import Path

import pytest

from forge.components._registry import COMPONENT_REGISTRY
from forge.config import (
    BackendConfig,
    BackendLanguage,
    FrontendConfig,
    FrontendFramework,
    ProjectConfig,
)
from forge.fragments import FRAGMENT_REGISTRY
from forge.generator import generate

# (component name, fragment name, the primary emitted file relative to the app root)
PRIMITIVES = [
    ("Switch", "component_Switch", "shared/ui/switch/Switch.vue"),
    ("StatusDot", "component_StatusDot", "shared/ui/status-dot/StatusDot.vue"),
    ("PageActionGroup", "component_PageActionGroup", "shared/ui/page-actions/PageActionGroup.vue"),
]


def _gen(tmp_path: Path, components: list[str]) -> Path:
    fc = FrontendConfig(framework=FrontendFramework.VUE, project_name="N", server_port=5173)
    cfg = ProjectConfig(
        project_name="N",
        output_dir=str(tmp_path),
        backends=[
            BackendConfig(
                name="api", project_name="N", language=BackendLanguage.PYTHON, features=["items"]
            )
        ],
        frontend=fc,
        components=components,
    )
    return Path(generate(cfg, quiet=True, dry_run=True))


@pytest.mark.parametrize(("name", "fragment", "_file"), PRIMITIVES)
def test_component_autoregistered(name: str, fragment: str, _file: str) -> None:
    assert name in COMPONENT_REGISTRY
    assert fragment in FRAGMENT_REGISTRY
    assert COMPONENT_REGISTRY[name].layer == 1


@pytest.mark.parametrize(("name", "_fragment", "file"), PRIMITIVES)
def test_absent_by_default(tmp_path: Path, name: str, _fragment: str, file: str) -> None:
    root = _gen(tmp_path, [])
    assert not list(root.rglob(file)), f"{name} must be absent when not selected"


@pytest.mark.parametrize(("name", "_fragment", "file"), PRIMITIVES)
def test_emitted_when_selected(tmp_path: Path, name: str, _fragment: str, file: str) -> None:
    root = _gen(tmp_path, [name])
    matches = list(root.rglob(file))
    assert len(matches) == 1, f"expected exactly one {file} for {name}, found {matches}"
    # The barrel re-export ships alongside the component.
    index = matches[0].parent / "index.ts"
    assert index.is_file(), f"{name} must ship an index.ts barrel"


def test_primitives_compose_together(tmp_path: Path) -> None:
    """All three can be selected at once with no file-overlap conflict."""
    root = _gen(tmp_path, [n for n, _, _ in PRIMITIVES])
    for _name, _fragment, file in PRIMITIVES:
        assert list(root.rglob(file))


def test_switch_uses_radix(tmp_path: Path) -> None:
    root = _gen(tmp_path, ["Switch"])
    src = next(root.rglob("shared/ui/switch/Switch.vue")).read_text(encoding="utf-8")
    assert "radix-vue" in src
    assert "SwitchRoot" in src
