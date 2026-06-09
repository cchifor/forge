"""Invariants for the ``DataTable`` Layer-1 component feature.

Opt-in (selected via ``ProjectConfig.components``), so it's absent from every
golden preset; when selected it emits the TanStack-Table data grid + the column
management composables + ``ColumnManagerMenu`` and its self-contained
``checkbox`` / ``popover`` primitives into the Vue app.
"""

from __future__ import annotations

from pathlib import Path

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


def _one(root: Path, rel: str) -> Path:
    matches = list(root.rglob(rel))
    assert len(matches) == 1, f"expected exactly one {rel}, found {matches}"
    return matches[0]


def test_component_autoregistered() -> None:
    assert "DataTable" in COMPONENT_REGISTRY
    assert "component_DataTable" in FRAGMENT_REGISTRY


def test_absent_by_default(tmp_path: Path) -> None:
    root = _gen(tmp_path, [])
    assert not list(root.rglob("shared/ui/data-table/DataTable.vue"))


def test_emitted_when_selected(tmp_path: Path) -> None:
    root = _gen(tmp_path, ["DataTable"])
    for rel in (
        "shared/ui/data-table/DataTable.vue",
        "shared/ui/data-table/ColumnManagerMenu.vue",
        "shared/ui/data-table/SortChip.vue",
        "shared/ui/data-table/useDataTable.ts",
        "shared/ui/data-table/useColumnManager.ts",
        "shared/ui/data-table/useColumnVisibility.ts",
        "shared/ui/data-table/useColumnOrder.ts",
        "shared/ui/data-table/useColumnPinning.ts",
        "shared/ui/data-table/useColumnSizing.ts",
        "shared/ui/data-table/augmentedColumns.ts",
        "shared/ui/data-table/breakpoints.ts",
        "shared/ui/data-table/types.ts",
        "shared/ui/data-table/index.ts",
        # self-contained local primitives shipped with the feature
        "shared/ui/data-table/checkbox/index.ts",
        "shared/ui/data-table/checkbox/Checkbox.vue",
        "shared/ui/data-table/popover/index.ts",
        "shared/ui/data-table/popover/PopoverContent.vue",
    ):
        _one(root, rel)


def test_emitted_files_are_platform_free(tmp_path: Path) -> None:
    root = _gen(tmp_path, ["DataTable"])
    dt = _one(root, "shared/ui/data-table/DataTable.vue").parent

    # Exclude co-located test files: they mention the removed dependency in
    # explanatory comments. The contract is that no *source* file imports it.
    blob = "\n".join(
        p.read_text(encoding="utf-8")
        for p in dt.rglob("*")
        if p.suffix in {".ts", ".vue"} and not p.name.endswith(".test.ts")
    )
    # Ported clean: no private weld SDK, no extra drag-and-drop npm dependency.
    assert "weld" not in blob
    assert "vue-draggable-plus" not in blob

    # ColumnManagerMenu resolves the primitives locally, never via the shared
    # popover the NotificationCenter feature ships.
    manager = _one(root, "shared/ui/data-table/ColumnManagerMenu.vue").read_text(
        encoding="utf-8"
    )
    assert "@/shared/ui/popover" not in manager
    assert "@/shared/ui/checkbox" not in manager
    assert "from './popover'" in manager
    assert "from './checkbox'" in manager

    # useDataTable also resolves the checkbox locally.
    use_dt = _one(root, "shared/ui/data-table/useDataTable.ts").read_text(
        encoding="utf-8"
    )
    assert "@/shared/ui/checkbox" not in use_dt
    assert "from './checkbox'" in use_dt

    # DataTable.vue keeps the base composable import as-is.
    data_table = _one(root, "shared/ui/data-table/DataTable.vue").read_text(
        encoding="utf-8"
    )
    assert "@/shared/composables/useContainerSize" in data_table
