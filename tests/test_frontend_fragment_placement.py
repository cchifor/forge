"""A project-scoped, frontend-targeted fragment's files must land in the Vue
app dir (apps/<slug>/), not at the project root — so generated components are
inside the app that builds them. (Codex Phase-3 BLOCKER.)"""

from __future__ import annotations

from pathlib import Path

from forge.capability_resolver import ResolvedFragment
from forge.config import BackendLanguage, FrontendFramework
from forge.fragments import Fragment, FragmentImplSpec
from forge.sync.forge_to_project import apply_project_features


def _frontend_fragment(tmp_path: Path) -> ResolvedFragment:
    frag_dir = tmp_path / "tpl" / "component_Widget" / "all"
    comp = frag_dir / "files" / "src" / "shared" / "components"
    comp.mkdir(parents=True)
    (comp / "Widget.vue").write_text("<template><div /></template>\n", encoding="utf-8")
    frag = Fragment(
        name="component_Widget",
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(fragment_dir=str(frag_dir), scope="project")
        },
        target_frontends=(FrontendFramework.VUE,),
        frontend_skip_reason="Vue-first.",
    )
    return ResolvedFragment(fragment=frag, target_backends=(BackendLanguage.PYTHON,))


def test_frontend_fragment_lands_in_app_dir(tmp_path: Path) -> None:
    rf = _frontend_fragment(tmp_path)
    project_root = tmp_path / "proj"
    frontend_dir = project_root / "apps" / "web"
    frontend_dir.mkdir(parents=True)

    apply_project_features(
        project_root,
        (rf,),
        quiet=True,
        frontend_framework=FrontendFramework.VUE,
        frontend_dir=frontend_dir,
    )

    assert (frontend_dir / "src" / "shared" / "components" / "Widget.vue").is_file()
    # Must NOT leak into the orphaned project-root src/.
    assert not (project_root / "src" / "shared" / "components" / "Widget.vue").exists()


def test_non_component_frontend_fragment_stays_at_root(tmp_path: Path) -> None:
    # Scoping: only ``component_*`` fragments are routed into the app dir, so
    # existing frontend fragments (auth, etc.) keep their current placement and
    # golden snapshots are unaffected.
    rf = _frontend_fragment(tmp_path)
    # Rename the fragment so it is NOT a component emitter.
    plain = Fragment(
        name="platform_auth_session_timeout_vue",
        implementations=rf.fragment.implementations,
        target_frontends=(FrontendFramework.VUE,),
        frontend_skip_reason="x",
    )
    rf = ResolvedFragment(fragment=plain, target_backends=(BackendLanguage.PYTHON,))
    project_root = tmp_path / "proj"
    frontend_dir = project_root / "apps" / "web"
    frontend_dir.mkdir(parents=True)
    apply_project_features(
        project_root, (rf,), quiet=True, frontend_framework=FrontendFramework.VUE, frontend_dir=frontend_dir
    )
    assert (project_root / "src" / "shared" / "components" / "Widget.vue").is_file()
    assert not (frontend_dir / "src" / "shared" / "components" / "Widget.vue").exists()


def test_without_frontend_dir_keeps_legacy_root_placement(tmp_path: Path) -> None:
    # Back-compat: when frontend_dir isn't passed (updater path), behavior is
    # unchanged — files land at project_root.
    rf = _frontend_fragment(tmp_path)
    project_root = tmp_path / "proj"
    project_root.mkdir()
    apply_project_features(
        project_root, (rf,), quiet=True, frontend_framework=FrontendFramework.VUE
    )
    assert (project_root / "src" / "shared" / "components" / "Widget.vue").is_file()
