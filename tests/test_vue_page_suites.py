"""The rendered Vue application's integration suite exercises its pages.

The Vue coverage gate unions Vitest/V8 line coverage with instrumented browser
coverage. The two map compiled single-file components back to source
differently, so a bundler source-map change can drop page template lines from
the browser numerator while V8 still counts them. Rolldown 1.2.14 did exactly
that (generated-quality run 38364234081: 1045/1278 became 973/1230). Pages are
therefore also mounted in the integration suite, which V8 measures with the
same mapping as the denominator. These tests pin that every generated CRUD
feature gets its page contract, bound to that feature's mock API.

Uses ``dry_run=True`` so rendering happens without the post-generate npm tasks
(same approach as ``test_golden_snapshots``).
"""

from __future__ import annotations

import shutil
from collections.abc import Callable, Iterator
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

_PAGE_SUITES = {"crud.ts", "home-page.test.ts", "profile-page.test.ts", "settings-page.test.ts"}
_COMPONENT_SUITES = {
    "button.test.ts",
    "primitives.test.ts",
    "splitter.test.ts",
    "status-confirmation.test.ts",
}


Render = Callable[[dict[str, list[str]]], Path]


@pytest.fixture
def render() -> Iterator[Render]:
    """Render Vue frontends for the given backend features; remove them afterwards."""
    roots: list[Path] = []

    def _render(backends: dict[str, list[str]]) -> Path:
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
                include_auth=False,
                include_chat=False,
                include_openapi=False,
            ),
        )
        roots.append(Path(generate(config, quiet=True, dry_run=True)))
        return roots[-1] / "apps" / "frontend"

    yield _render
    for root in roots:
        # dry_run renders into its own temporary directory.
        shutil.rmtree(root.parent, ignore_errors=True)


def test_each_feature_runs_the_page_contract_against_its_own_mock_api(render: Render) -> None:
    frontend = render({"api": ["items"], "shop": ["orders"]})
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


def test_a_frontend_without_features_ships_only_the_shared_suites(render: Render) -> None:
    integration = render({"api": []}) / "tests" / "integration"
    assert {path.name for path in integration.iterdir()} == _PAGE_SUITES | _COMPONENT_SUITES
