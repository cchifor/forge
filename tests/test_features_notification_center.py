"""Invariants for the ``NotificationCenter`` Layer-2 component feature.

Opt-in (selected via ``ProjectConfig.components``), so it's absent from every
golden preset; when selected it emits the notifications feature module + the
supporting Popover/RelativeTime/formatTime primitives into the Vue app.
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
    assert "NotificationCenter" in COMPONENT_REGISTRY
    assert "component_NotificationCenter" in FRAGMENT_REGISTRY


def test_absent_by_default(tmp_path: Path) -> None:
    root = _gen(tmp_path, [])
    assert not list(root.rglob("features/notifications/store.ts"))


def test_emitted_when_selected(tmp_path: Path) -> None:
    root = _gen(tmp_path, ["NotificationCenter"])
    for rel in (
        "features/notifications/store.ts",
        "features/notifications/toast.ts",
        "features/notifications/invalidation.ts",
        "features/notifications/api/stream.ts",
        "features/notifications/api/client.ts",
        "features/notifications/composables/useNotifications.ts",
        "features/notifications/components/NotificationBell.vue",
        "features/notifications/components/NotificationCenter.vue",
        "features/notifications/components/ToastHost.vue",
        "features/notifications/index.ts",
        # supporting primitives shipped with the feature
        "shared/ui/popover/index.ts",
        "shared/components/RelativeTime.vue",
        "shared/lib/formatTime.ts",
    ):
        _one(root, rel)


def test_composes_popover_primitive_without_collision(tmp_path: Path) -> None:
    """NotificationCenter sources shared/ui/popover/ from the Popover primitive.

    It declares ``Popover`` as a child component rather than shipping its own
    inlined copy, so selecting both ``NotificationCenter`` and ``Popover``
    together emits the popover files exactly once (no strict file-copy clash).
    """
    # Child pull: NotificationCenter alone still materializes the popover.
    root = _gen(tmp_path / "a", ["NotificationCenter"])
    assert "Popover" in COMPONENT_REGISTRY
    assert len(list(root.rglob("shared/ui/popover/PopoverContent.vue"))) == 1

    # Co-selection must not collide on the shared path.
    both = _gen(tmp_path / "b", ["NotificationCenter", "Popover"])
    assert len(list(both.rglob("shared/ui/popover/PopoverContent.vue"))) == 1
    assert len(list(both.rglob("shared/ui/popover/index.ts"))) == 1


def test_builds_on_useeventstream_and_is_platform_free(tmp_path: Path) -> None:
    root = _gen(tmp_path, ["NotificationCenter"])
    nf = _one(root, "features/notifications/store.ts").parent
    stream = (nf / "api" / "stream.ts").read_text(encoding="utf-8")
    assert "@/shared/composables/useEventStream" in stream
    blob = "\n".join(p.read_text(encoding="utf-8") for p in nf.rglob("*.ts"))
    # Ported clean: no private weld SDK, no platform-only endpoints.
    assert "weld" not in blob
    assert "api/notification/v1" not in blob
    # The toast.message bug (called by the panel, missing on platform) is fixed.
    assert "message:" in (nf / "toast.ts").read_text(encoding="utf-8")
