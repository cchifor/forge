"""Standalone-build gate (P5): a generated Python project builds with NO weld.

The keystone of the weld-decoupling effort: a generated project must resolve,
type-check, and pass its own test suite *without* any ``weld-*`` package being
installable — the always-shipped ``forge-core`` SDK (vendored inside each
backend at ``sdks/forge-core/``) is enough. Unlike :mod:`test_full_generation`,
this test deliberately does NOT inject the matrix weld stubs: if the generated
project still imports weld anywhere, ``uv sync`` / ``pytest`` would fail.

Two postures are exercised, both of which must come out weld-free:

* **auth off** (``auth.mode=none``) — the minimal default project.
* **auth.mode=generate** — the full platform-auth stack (SDK at
  ``sdks/platform-auth/`` + middleware fragment + gatekeeper-provider config).

Marked ``@pytest.mark.e2e`` (heavy / opt-in like the other scaffold-and-run
tests). Run explicitly with ``pytest -m e2e -k standalone_build``.
"""

from __future__ import annotations

import ast
import subprocess
from pathlib import Path

import pytest

from forge.config import (
    BackendConfig,
    BackendLanguage,
    ProjectConfig,
)
from forge.generator import generate

pytestmark = pytest.mark.e2e

TEST_TIMEOUT_S = 600


def _run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    import shutil as _shutil

    resolved = _shutil.which(cmd[0])
    if resolved is not None:
        cmd = [resolved, *cmd[1:]]
    return subprocess.run(
        cmd,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=TEST_TIMEOUT_S,
        check=False,
    )


def _python_files(root: Path) -> list[Path]:
    return [
        p
        for p in root.rglob("*.py")
        if "__pycache__" not in p.parts and ".venv" not in p.parts
    ]


def _grep_weld(root: Path) -> list[str]:
    """Return every ``import weld`` / ``from weld`` occurrence under ``root``."""
    hits: list[str] = []
    for p in _python_files(root):
        for lineno, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith(("import weld", "from weld")):
                hits.append(f"{p}:{lineno}:{stripped}")
    # pyproject / lock references too
    for name in ("pyproject.toml", "uv.lock"):
        for p in root.rglob(name):
            if ".venv" in p.parts:
                continue
            text = p.read_text(encoding="utf-8")
            for lineno, line in enumerate(text.splitlines(), 1):
                if "weld-" in line or "weld_" in line:
                    hits.append(f"{p}:{lineno}:{line.strip()}")
    return hits


def _assert_ast_parses(root: Path) -> None:
    for p in _python_files(root):
        source = p.read_text(encoding="utf-8")
        ast.parse(source, filename=str(p))


def _minimal_config(tmp_path: Path) -> ProjectConfig:
    return ProjectConfig(
        project_name="Standalone Minimal",
        output_dir=str(tmp_path),
        backends=[
            BackendConfig(
                name="svc",
                project_name="Standalone Minimal",
                language=BackendLanguage.PYTHON,
                features=["items"],
                # No sibling sdks/ tree in this standalone tmp build.
                sdk_consumption="none",
            )
        ],
        frontend=None,
    )


def _auth_config(tmp_path: Path) -> ProjectConfig:
    return ProjectConfig(
        project_name="Standalone Auth",
        output_dir=str(tmp_path),
        backends=[
            BackendConfig(
                name="svc",
                project_name="Standalone Auth",
                language=BackendLanguage.PYTHON,
                features=["items"],
                sdk_consumption="none",
            )
        ],
        frontend=None,
        include_keycloak=True,
        options={"auth.mode": "generate", "auth.provider": "gatekeeper"},
    )


def _build_and_test(backend_dir: Path) -> None:
    """uv sync (no weld available) + run the generated project's pytest."""
    sync = _run(["uv", "sync"], cwd=backend_dir)
    assert sync.returncode == 0, f"uv sync failed (weld-free):\n{sync.stderr}"
    result = _run(["uv", "run", "pytest", "-x", "--no-cov", "-q"], cwd=backend_dir)
    assert result.returncode == 0, (
        f"generated python backend tests failed:\n"
        f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )


def test_minimal_project_builds_weld_free(
    tmp_path: Path, require_uv: None, require_git: None
) -> None:
    """auth.mode=none default project: zero weld, deps resolve, tests pass."""
    project_root = generate(_minimal_config(tmp_path), quiet=True)

    weld_hits = _grep_weld(project_root)
    assert not weld_hits, "weld references in a minimal project:\n" + "\n".join(weld_hits)
    _assert_ast_parses(project_root)

    backend_dir = project_root / "services" / "svc"
    assert backend_dir.is_dir()
    _build_and_test(backend_dir)


def test_auth_generate_project_builds_weld_free(
    tmp_path: Path, require_uv: None, require_git: None
) -> None:
    """auth.mode=generate (gatekeeper) project: zero weld, deps resolve, tests pass."""
    project_root = generate(_auth_config(tmp_path), quiet=True)

    weld_hits = _grep_weld(project_root)
    assert not weld_hits, "weld references in an auth project:\n" + "\n".join(weld_hits)
    _assert_ast_parses(project_root)

    backend_dir = project_root / "services" / "svc"
    assert backend_dir.is_dir()
    # The platform-auth SDK ships at the project root; it must be present.
    assert (project_root / "sdks" / "platform-auth").is_dir()
    _build_and_test(backend_dir)
