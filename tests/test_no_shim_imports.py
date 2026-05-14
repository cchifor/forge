"""Regression: no forge/ module imports the (now-deleted) feature_injector shim."""

import ast
from pathlib import Path

import pytest

_FORGE_ROOT = Path(__file__).resolve().parent.parent / "forge"


@pytest.mark.parametrize("py_file", sorted(_FORGE_ROOT.rglob("*.py")))
def test_no_imports_of_feature_injector(py_file: Path) -> None:
    tree = ast.parse(py_file.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "forge.feature_injector":
            pytest.fail(
                f"{py_file.relative_to(_FORGE_ROOT.parent)} imports from forge.feature_injector — "
                "shim was deleted; use forge.sync.forge_to_project / forge.injectors / forge.appliers instead."
            )
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "forge.feature_injector":
                    pytest.fail(
                        f"{py_file.relative_to(_FORGE_ROOT.parent)} imports forge.feature_injector — "
                        "shim was deleted."
                    )
