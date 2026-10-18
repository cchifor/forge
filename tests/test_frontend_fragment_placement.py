"""A project-scoped fragment that declares ``target_frontends`` ships app-relative
files (``files/src/...``): they must land in the frontend app (apps/<slug>/),
never at the project root, so the generated code is inside the app that builds
it. A frontend-agnostic project fragment still emits at the project root."""

from __future__ import annotations

from pathlib import Path

import pytest

from forge.capability_resolver import ResolvedFragment
from forge.config import BackendLanguage, FrontendFramework
from forge.fragments import Fragment, FragmentImplSpec
from forge.sync.forge_to_project import apply_project_features


def _fragment(
    tmp_path: Path, name: str, *, target_frontends: tuple[FrontendFramework, ...]
) -> ResolvedFragment:
    frag_dir = tmp_path / "tpl" / name / "all"
    comp = frag_dir / "files" / "src" / "shared" / "components"
    comp.mkdir(parents=True)
    (comp / "Widget.vue").write_text("<template><div /></template>\n", encoding="utf-8")
    frag = Fragment(
        name=name,
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(fragment_dir=str(frag_dir), scope="project")
        },
        target_frontends=target_frontends,
        frontend_skip_reason="Vue-first.",
    )
    return ResolvedFragment(fragment=frag, target_backends=(BackendLanguage.PYTHON,))


@pytest.mark.parametrize(
    "name",
    [
        # A layered-component emitter, the first fragment routed into the app.
        "component_Widget",
        # Any other frontend-targeted fragment: placement follows the declaration,
        # not the name (the session-timeout fragments used to land at the root).
        "platform_auth_session_timeout_vue",
    ],
)
def test_frontend_targeted_fragment_lands_in_app_dir(tmp_path: Path, name: str) -> None:
    rf = _fragment(tmp_path, name, target_frontends=(FrontendFramework.VUE,))
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
    # Must NOT leak into an orphaned project-root src/.
    assert not (project_root / "src").exists()


@pytest.mark.parametrize("framework", [FrontendFramework.VUE, None])
def test_frontend_targeted_fragment_without_app_dir_is_skipped(
    tmp_path: Path, framework: FrontendFramework | None
) -> None:
    # No app directory means no correct place for app-relative files: the
    # fragment is skipped instead of being written at the project root, also
    # when the caller does not know the frontend (framework None).
    rf = _fragment(tmp_path, "component_Widget", target_frontends=(FrontendFramework.VUE,))
    project_root = tmp_path / "proj"
    project_root.mkdir()

    apply_project_features(project_root, (rf,), quiet=True, frontend_framework=framework)

    assert list(project_root.iterdir()) == []


def test_frontend_agnostic_project_fragment_stays_at_root(tmp_path: Path) -> None:
    rf = _fragment(tmp_path, "project_docs", target_frontends=())
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

    assert (project_root / "src" / "shared" / "components" / "Widget.vue").is_file()
    assert not (frontend_dir / "src").exists()


@pytest.mark.parametrize(
    ("framework", "app_dir", "expected"),
    [
        (FrontendFramework.VUE, "apps/web", "apps/web"),
        (FrontendFramework.SVELTE, "", "apps/frontend"),
        (FrontendFramework.NONE, "apps/frontend", None),
    ],
)
def test_update_places_frontend_fragments_in_the_recorded_app(
    tmp_path: Path, framework: FrontendFramework, app_dir: str, expected: str | None
) -> None:
    # --update and --plan-update use the manifest's app_dir, falling back to
    # the generator's fixed apps/frontend; a project without a frontend has none.
    from forge.sync.forge_to_project.updater import frontend_app_dir
    from forge.sync.manifest import ForgeFrontendData

    found = frontend_app_dir(
        tmp_path, ForgeFrontendData(framework=framework.value, app_dir=app_dir), framework
    )
    assert found == (tmp_path / expected if expected else None)


@pytest.mark.parametrize(
    ("pubspec", "package"),
    [
        # A Flutter app keeps its pubspec name wherever its directory is.
        ("name: frontend\ndescription: app\n", "frontend"),
        # Without a pubspec the app directory's name stands in.
        (None, "mobile"),
    ],
)
def test_frontend_fragment_renders_the_app_package_name(
    tmp_path: Path, pubspec: str | None, package: str
) -> None:
    frag_dir = tmp_path / "tpl" / "flutter_probe" / "all"
    test_dir = frag_dir / "files" / "test"
    test_dir.mkdir(parents=True)
    (test_dir / "probe_test.dart.jinja").write_text(
        "import 'package:{{ project_slug }}/src/probe.dart';\n", encoding="utf-8"
    )
    frag = Fragment(
        name="flutter_probe",
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(fragment_dir=str(frag_dir), scope="project")
        },
        target_frontends=(FrontendFramework.FLUTTER,),
        frontend_skip_reason="Flutter-only probe.",
    )
    project_root = tmp_path / "proj"
    frontend_dir = project_root / "apps" / "mobile"
    frontend_dir.mkdir(parents=True)
    if pubspec is not None:
        (frontend_dir / "pubspec.yaml").write_text(pubspec, encoding="utf-8")

    apply_project_features(
        project_root,
        (ResolvedFragment(fragment=frag, target_backends=(BackendLanguage.PYTHON,)),),
        quiet=True,
        frontend_framework=FrontendFramework.FLUTTER,
        frontend_dir=frontend_dir,
    )

    rendered = (frontend_dir / "test" / "probe_test.dart").read_text(encoding="utf-8")
    assert rendered == f"import 'package:{package}/src/probe.dart';\n"
