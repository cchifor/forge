"""The rendered Vue application's integration suite exercises its pages.

The Vue coverage gate unions Vitest/V8 line coverage with instrumented browser
coverage. The two map compiled single-file components back to source
differently, so a bundler source-map change can drop page template lines from
the browser numerator while V8 still counts them. Rolldown 1.2.14 did exactly
that (generated-quality run 38364234081: 1045/1278 became 973/1230). Pages are
therefore also mounted in the integration suite, which V8 measures with the
same mapping as the denominator. These tests pin that every generated CRUD
feature gets its page contract, bound to that feature's mock API; that the home
page only links to generated routes; that the profile suite exercises the
project's authentication variant; and that updates keep edited page tests.

Uses ``dry_run=True`` so rendering happens without the post-generate npm tasks
(same approach as ``test_golden_snapshots``).
"""

from __future__ import annotations

import re
import shutil
from collections.abc import Callable, Iterator
from pathlib import Path

import copier
import pytest
import yaml

from forge.config import (
    BackendConfig,
    BackendLanguage,
    FrontendConfig,
    FrontendFramework,
    ProjectConfig,
)
from forge.generator import generate
from forge.quality.update import update_owned_project

_PAGE_SUITES = {"crud.ts", "home-page.test.ts", "profile-page.test.ts", "settings-page.test.ts"}
_COMPONENT_SUITES = {
    "button.test.ts",
    "primitives.test.ts",
    "splitter.test.ts",
    "status-confirmation.test.ts",
}
_EDIT = "\n// Project-specific page case kept across updates.\n"

Render = Callable[..., Path]


@pytest.fixture
def render() -> Iterator[Render]:
    """Render projects with a Vue frontend; remove them afterwards."""
    roots: list[Path] = []

    def _render(backends: dict[str, list[str]], *, auth: bool = False) -> Path:
        config = ProjectConfig(
            project_name="pages",
            backends=[
                BackendConfig(
                    name=name,
                    project_name="pages",
                    language=BackendLanguage.PYTHON,
                    server_port=5000 + index,
                    features=features,
                )
                for index, (name, features) in enumerate(backends.items(), 1)
            ],
            frontend=FrontendConfig(
                project_name="frontend",
                framework=FrontendFramework.VUE,
                include_auth=auth,
                include_chat=False,
                include_openapi=False,
            ),
        )
        roots.append(Path(generate(config, quiet=True, dry_run=True)))
        return roots[-1]

    yield _render
    for root in roots:
        # dry_run renders into its own temporary directory.
        shutil.rmtree(root.parent, ignore_errors=True)


def _frontend(root: Path) -> Path:
    return root / "apps" / "frontend"


@pytest.mark.parametrize("auth", [False, True], ids=["auth-off", "auth-on"])
def test_each_feature_runs_the_page_contract_against_its_own_mock_api(
    render: Render, auth: bool
) -> None:
    frontend = _frontend(render({"api": ["items"], "shop": ["orders"]}, auth=auth))
    integration = frontend / "tests" / "integration"
    assert {path.name for path in integration.iterdir()} >= _PAGE_SUITES
    for plural, singular, backend in (("items", "item", "api"), ("orders", "order", "shop")):
        assert (integration / f"{plural}.test.ts").read_text(encoding="utf-8") == (
            f"import {{ {plural}Routes }} from '../../src/features/{plural}'\n"
            "import { testCrud } from './crud'\n"
            f"testCrud('{plural}', '{singular}', '{backend}', {plural}Routes)\n"
        )
        index = (frontend / "src" / "features" / plural / "index.ts").read_text(encoding="utf-8")
        assert f"export const {plural}Routes = [" in index
        handlers = frontend / "src" / "shared" / "mocks" / f"{plural}.handlers.ts"
        assert f"http.get('*/api/{backend}/v1/{plural}'," in handlers.read_text(encoding="utf-8")


@pytest.mark.parametrize("auth", [False, True], ids=["auth-off", "auth-on"])
def test_a_frontend_without_features_ships_only_the_shared_suites(
    render: Render, auth: bool
) -> None:
    integration = _frontend(render({"api": []}, auth=auth)) / "tests" / "integration"
    assert {path.name for path in integration.iterdir()} == _PAGE_SUITES | _COMPONENT_SUITES


@pytest.mark.parametrize(
    "features", [[], ["orders"], ["items", "orders"]], ids=["no-features", "orders", "items+orders"]
)
def test_home_quick_actions_lead_only_to_generated_routes(
    render: Render, features: list[str]
) -> None:
    frontend = _frontend(render({"api": features}))
    home = (frontend / "src" / "features" / "home" / "ui" / "HomePage.vue").read_text(
        encoding="utf-8"
    )
    expected = {"/profile", "/settings"}
    for plural in features:
        index = (frontend / "src" / "features" / plural / "index.ts").read_text(encoding="utf-8")
        assert f"path: '{plural}'," in index and f"path: '{plural}/new'," in index
        expected |= {f"/{plural}", f"/{plural}/new"}
    assert set(re.findall(r"route: '([^']+)'", home)) == expected
    # vue-tsc rejects unused icon imports (noUnusedLocals).
    imported = re.search(r"import \{ ([^}]+) \} from '@lucide/vue'", home)
    assert imported is not None
    for icon in imported.group(1).split(", "):
        assert re.search(rf"icon: {icon}\b|<{icon}\b", home), f"{icon} imported but unused"


@pytest.mark.parametrize("auth", [False, True], ids=["auth-off", "auth-on"])
def test_profile_suite_exercises_the_projects_authentication(render: Render, auth: bool) -> None:
    frontend = _frontend(render({"api": []}, auth=auth))
    suite = (frontend / "tests" / "integration" / "profile-page.test.ts").read_text(
        encoding="utf-8"
    )
    use_auth = (frontend / "src" / "shared" / "composables" / "useAuth.ts").read_text(
        encoding="utf-8"
    )
    assert "VITE_AUTH_DISABLED" not in suite
    if auth:
        # The suite answers the request the gateway-backed composable makes.
        assert "fetch('/auth/userinfo'" in use_auth
        assert "http.get('*/auth/userinfo'" in suite
        assert "'Ada Lovelace'" in suite
    else:
        assert "/auth/userinfo" not in use_auth
        assert "userinfo" not in suite
        assert "'Dev User'" in suite


def test_ownership_managed_update_keeps_an_edited_page_test(render: Render) -> None:
    root = render({"api": ["items"]})
    page_test = _frontend(root) / "tests" / "integration" / "items.test.ts"
    page_test.write_text(page_test.read_text(encoding="utf-8") + _EDIT, encoding="utf-8")
    report = update_owned_project(root)
    assert report["passed"], report
    assert page_test.read_text(encoding="utf-8").endswith(_EDIT)
    assert not page_test.with_name(page_test.name + ".forge-merge").exists()


def test_rerunning_the_copier_task_keeps_edited_and_restores_missing_page_tests(
    render: Render, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`copier update` re-renders the app in place and re-runs post_generate.py."""
    frontend = _frontend(render({"api": ["items", "orders"]}))
    integration = frontend / "tests" / "integration"
    edited, removed = integration / "items.test.ts", integration / "orders.test.ts"
    edited.write_text(edited.read_text(encoding="utf-8") + _EDIT, encoding="utf-8")
    original = removed.read_text(encoding="utf-8")
    removed.unlink()
    answers = yaml.safe_load((frontend / ".copier-answers.yml").read_text(encoding="utf-8"))
    monkeypatch.setenv("FORGE_RENDER_ONLY", "1")  # skip npm install and git in the task
    copier.run_copy(
        src_path=answers["_src_path"],
        dst_path=str(frontend),
        data={key: value for key, value in answers.items() if not key.startswith("_")},
        defaults=True,
        overwrite=True,
        unsafe=True,
        quiet=True,
    )
    assert edited.read_text(encoding="utf-8").endswith(_EDIT)
    assert removed.read_text(encoding="utf-8") == original
