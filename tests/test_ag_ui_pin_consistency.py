"""Drift gate for the `@ag-ui/client` / `@ag-ui/core` version pin.

The Vue + Svelte frontend templates and the in-tree `packages/canvas-vue` /
`packages/canvas-svelte` packages all depend on the same AG-UI client and
core packages. Historically each location hardcoded its own ``^0.0.51``
string, so a bump required four edits and a forgotten one caused
type-drift skips (see ``known-issues.md`` re ``svelte_chat_on_typechecks``).

This test pins the version in one place
(``forge.codegen.event_union.AG_UI_CLIENT_VERSION`` /
``AG_UI_CORE_VERSION``) and asserts every consumer matches it:

* Vue + Svelte frontend ``package.json.jinja`` templates consume the
  Copier vars ``ag_ui_client_version`` / ``ag_ui_core_version`` (rather
  than hardcoding) — checked by reading the template strings and
  asserting they reference the Jinja vars.
* ``packages/canvas-{vue,svelte}/package.json`` hardcode the pinned
  version directly (they're not Copier-rendered) — checked by parsing
  the JSON and comparing to the constants.

Bump procedure (when AG-UI moves):
  1. Change the two constants in ``forge/codegen/event_union.py``.
  2. Edit ``packages/canvas-vue/package.json`` and
     ``packages/canvas-svelte/package.json`` to match.
  3. Run ``pytest tests/test_ag_ui_pin_consistency.py`` to verify.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from forge.codegen.event_union import AG_UI_CLIENT_VERSION, AG_UI_CORE_VERSION

REPO_ROOT = Path(__file__).resolve().parent.parent

VUE_PKG = REPO_ROOT / "packages" / "canvas-vue" / "package.json"
SVELTE_PKG = REPO_ROOT / "packages" / "canvas-svelte" / "package.json"

VUE_TPL = (
    REPO_ROOT
    / "forge"
    / "templates"
    / "apps"
    / "vue-frontend-template"
    / "template"
    / "package.json.jinja"
)
SVELTE_TPL = (
    REPO_ROOT
    / "forge"
    / "templates"
    / "apps"
    / "svelte-frontend-template"
    / "template"
    / "package.json.jinja"
)


def _dep_version(pkg_json_path: Path, dep_name: str) -> str:
    """Extract ``dependencies[dep_name]`` (or peerDependencies fallback) verbatim."""
    data = json.loads(pkg_json_path.read_text(encoding="utf-8"))
    for section in ("dependencies", "peerDependencies", "devDependencies"):
        deps = data.get(section, {})
        if dep_name in deps:
            return str(deps[dep_name])
    pytest.fail(f"{dep_name} not found in {pkg_json_path}")


@pytest.mark.parametrize(
    ("pkg_path", "dep_name", "expected_version"),
    [
        (VUE_PKG, "@ag-ui/client", AG_UI_CLIENT_VERSION),
        (VUE_PKG, "@ag-ui/core", AG_UI_CORE_VERSION),
        (SVELTE_PKG, "@ag-ui/client", AG_UI_CLIENT_VERSION),
        (SVELTE_PKG, "@ag-ui/core", AG_UI_CORE_VERSION),
    ],
)
def test_canvas_package_pins_match_constant(
    pkg_path: Path, dep_name: str, expected_version: str
) -> None:
    """Canvas packages hardcode the pinned version; assert it matches."""
    actual = _dep_version(pkg_path, dep_name)
    # The package.json typically uses caret ranges (``^0.0.51``); strip
    # leading range qualifiers before comparing to the bare constant.
    bare = actual.lstrip("^~>=<")
    assert bare == expected_version, (
        f"{pkg_path.relative_to(REPO_ROOT)}::{dep_name} pins {actual!r} "
        f"but forge.codegen.event_union.{('AG_UI_CLIENT_VERSION' if 'client' in dep_name else 'AG_UI_CORE_VERSION')} "
        f"is {expected_version!r}. Bump both or revert one — see the test docstring."
    )


@pytest.mark.parametrize(
    ("tpl_path", "expected_jinja_var", "dep_name"),
    [
        (VUE_TPL, "ag_ui_client_version", "@ag-ui/client"),
        (VUE_TPL, "ag_ui_core_version", "@ag-ui/core"),
        (SVELTE_TPL, "ag_ui_client_version", "@ag-ui/client"),
        (SVELTE_TPL, "ag_ui_core_version", "@ag-ui/core"),
    ],
)
def test_frontend_template_uses_jinja_var_not_hardcoded(
    tpl_path: Path, expected_jinja_var: str, dep_name: str
) -> None:
    """Frontend templates must reference the Jinja var, not a literal version.

    Prevents regression where someone hardcodes a new version in the
    template instead of bumping the central constant. We look for the
    ``{{ var }}`` interpolation on the same line as the dep name.
    """
    text = tpl_path.read_text(encoding="utf-8")
    # Find the line containing the dependency declaration.
    matching = [line for line in text.splitlines() if dep_name in line]
    assert matching, f"{dep_name} not found in {tpl_path}"
    # Each matching line should reference the Jinja var, not a hardcoded version.
    for line in matching:
        assert "{{ " + expected_jinja_var + " }}" in line or expected_jinja_var in line, (
            f"{tpl_path.relative_to(REPO_ROOT)} declares {dep_name} but does not "
            f"reference {{{{ {expected_jinja_var} }}}}: {line.strip()!r}. "
            f"The pin must be driven by forge/codegen/event_union.py — see the "
            f"test docstring."
        )


def test_constants_match_each_other() -> None:
    """Today client+core ship aligned 0.0.x versions; assert this until upstream diverges.

    If AG-UI ever publishes different majors for client vs core, delete
    this test — it's a soft invariant, not a hard contract.
    """
    assert AG_UI_CLIENT_VERSION == AG_UI_CORE_VERSION, (
        f"AG-UI client + core versions diverged "
        f"({AG_UI_CLIENT_VERSION} vs {AG_UI_CORE_VERSION}). If intentional, "
        f"delete this test; otherwise re-align the two constants."
    )
