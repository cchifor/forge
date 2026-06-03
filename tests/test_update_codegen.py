"""`forge --update` re-runs codegen (Initiative C).

Historically ``run_codegen`` ran only at fresh ``generate()`` time, so codegen
changes (e.g. the ``apps/<slug>`` frontend relocation) never reached an existing
project through ``forge --update``. ``update_project`` now re-runs codegen and
prunes the pre-relocation orphaned ``frontend/`` tree.
"""

from __future__ import annotations

from pathlib import Path

from forge.config import BackendConfig, FrontendConfig, FrontendFramework, ProjectConfig
from forge.generator import generate
from forge.sync.forge_to_project.updater import update_project

_GEN_REL = Path("apps/frontend/src/features/ai_chat/ui_protocol.gen.ts")


def _vue_chat_project(tmp_path: Path) -> Path:
    cfg = ProjectConfig(
        project_name="UpdCodegen",
        output_dir=str(tmp_path),
        backends=[BackendConfig(project_name="UpdCodegen", features=["items"])],
        frontend=FrontendConfig(
            framework=FrontendFramework.VUE,
            project_name="UpdCodegen",
            include_chat=True,
            include_auth=False,
        ),
        options={"agent.tools": True},
    )
    cfg.validate()
    # dry_run keeps codegen but skips post-generate (npm install / git) for speed.
    return generate(cfg, quiet=True, dry_run=True)


def test_update_regenerates_deleted_frontend_codegen(tmp_path: Path) -> None:
    root = _vue_chat_project(tmp_path)
    gen = root / _GEN_REL
    assert gen.is_file(), "fresh generation should emit the chat ui_protocol codegen"
    gen.unlink()  # simulate missing/stale codegen (e.g. an older project)

    update_project(root, quiet=True, no_lock=True)

    assert gen.is_file(), "forge --update did not re-run codegen"


def test_update_prunes_orphaned_frontend_tree(tmp_path: Path) -> None:
    root = _vue_chat_project(tmp_path)
    # Simulate a pre-relocation project: stale codegen under the orphaned
    # project_root/frontend/ tree (the real app is apps/frontend/).
    stale = root / "frontend" / "src" / "features" / "ai_chat" / "ui_protocol.gen.ts"
    stale.parent.mkdir(parents=True, exist_ok=True)
    stale.write_text("// stale orphaned codegen\n", encoding="utf-8")

    update_project(root, quiet=True, no_lock=True)

    assert not stale.exists(), "orphaned frontend/ codegen was not pruned"
    # The real app's codegen stays intact.
    assert (root / _GEN_REL).is_file()


def test_update_preserves_non_codegen_files_under_frontend(tmp_path: Path) -> None:
    root = _vue_chat_project(tmp_path)
    keep = root / "frontend" / "NOTES.md"
    keep.parent.mkdir(parents=True, exist_ok=True)
    keep.write_text("user notes — not codegen\n", encoding="utf-8")
    stale = root / "frontend" / "src" / "features" / "ai_chat" / "ui_protocol.gen.ts"
    stale.parent.mkdir(parents=True, exist_ok=True)
    stale.write_text("// stale\n", encoding="utf-8")

    update_project(root, quiet=True, no_lock=True)

    assert not stale.exists(), "codegen should be pruned"
    assert keep.is_file(), "non-codegen files must be left untouched"
