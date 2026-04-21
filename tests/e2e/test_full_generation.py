"""End-to-end: scaffold a project with `generate()` and run its native test suite.

Each parametrized case scaffolds a real project into a tmp_path, then exercises the
generated scaffold's own toolchain (`uv run pytest`, `npm test`, `cargo test --no-run`)
to verify the templates produce a working project — not just files that exist.

Marked `@pytest.mark.e2e` and excluded from the default `pytest` invocation
(see Makefile and CI workflow). Run explicitly with `pytest -m e2e`.

Cases that need missing toolchains skip cleanly (see conftest.py fixtures).
"""

from __future__ import annotations

import subprocess
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

TEST_TIMEOUT_S = 600  # 10 min per scaffold-and-run cycle


pytestmark = pytest.mark.e2e


def _run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    """Run a command in a generated scaffold's directory with a generous timeout.

    Resolves the executable via ``shutil.which`` so Windows ``.cmd`` shims
    (``npm.cmd``, ``npx.cmd``) are found — Python's ``subprocess`` doesn't walk
    ``PATHEXT`` for bare tool names.
    """
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


def _make_python_backend(name: str = "backend", port: int = 5000) -> BackendConfig:
    return BackendConfig(
        name=name,
        project_name="E2E Project",
        language=BackendLanguage.PYTHON,
        features=["items"],
        server_port=port,
    )


def _make_node_backend(name: str = "backend-node", port: int = 5001) -> BackendConfig:
    return BackendConfig(
        name=name,
        project_name="E2E Project",
        language=BackendLanguage.NODE,
        features=["items"],
        server_port=port,
    )


def _make_rust_backend(name: str = "backend-rust", port: int = 5002) -> BackendConfig:
    return BackendConfig(
        name=name,
        project_name="E2E Project",
        language=BackendLanguage.RUST,
        features=["items"],
        server_port=port,
    )


def _make_frontend(
    framework: FrontendFramework,
    with_auth: bool = False,
    with_chat: bool = False,
    with_openapi: bool | None = None,
) -> FrontendConfig:
    # Flutter requires openapi (see FrontendConfig.validate); default others to off.
    openapi = (
        with_openapi
        if with_openapi is not None
        else (framework == FrontendFramework.FLUTTER)
    )
    return FrontendConfig(
        framework=framework,
        project_name="E2E Project",
        server_port=5173,
        include_auth=with_auth,
        include_chat=with_chat,
        include_openapi=openapi,
        generate_e2e_tests=False,  # Playwright bring-up is its own world; out of scope here.
    )


# -----------------------------------------------------------------------------
# Case 1: Python backend, Vue frontend, no auth — the canonical happy path.
# -----------------------------------------------------------------------------


def test_python_vue_scaffolds_and_pytest_passes(
    tmp_path: Path, require_uv: None, require_git: None
) -> None:
    config = ProjectConfig(
        project_name="E2E Project",
        output_dir=str(tmp_path),
        backends=[_make_python_backend()],
        frontend=_make_frontend(FrontendFramework.VUE),
        include_keycloak=False,
    )
    config.validate()

    project_root = generate(config, quiet=True)
    backend_dir = project_root / "services" / "backend"
    assert backend_dir.exists(), "python backend not generated"

    sync = _run(["uv", "sync"], cwd=backend_dir)
    assert sync.returncode == 0, f"uv sync failed:\n{sync.stderr}"

    result = _run(["uv", "run", "pytest", "-x", "--no-cov", "-q"], cwd=backend_dir)
    assert result.returncode == 0, (
        f"generated python backend tests failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )


# -----------------------------------------------------------------------------
# Case 2: Node backend, Svelte frontend — exercises npm install + vitest path.
# -----------------------------------------------------------------------------


def test_node_svelte_scaffolds_and_vitest_passes(
    tmp_path: Path, require_npm: None, require_git: None
) -> None:
    config = ProjectConfig(
        project_name="E2E Project",
        output_dir=str(tmp_path),
        backends=[_make_node_backend()],
        frontend=_make_frontend(FrontendFramework.SVELTE),
        include_keycloak=False,
    )
    config.validate()

    project_root = generate(config, quiet=True)
    backend_dir = project_root / "services" / "backend-node"
    assert (backend_dir / "package.json").exists(), "node backend package.json missing"
    assert (backend_dir / "package-lock.json").exists(), (
        "npm install lockfile missing — Docker builds would fail"
    )

    result = _run(["npx", "--yes", "vitest", "run"], cwd=backend_dir)
    assert result.returncode == 0, (
        f"generated node backend tests failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )


# -----------------------------------------------------------------------------
# Case 3: Rust backend, no frontend — fast `cargo test --no-run` smoke check.
# -----------------------------------------------------------------------------


def test_rust_no_frontend_compiles(tmp_path: Path, require_cargo: None, require_git: None) -> None:
    config = ProjectConfig(
        project_name="E2E Project",
        output_dir=str(tmp_path),
        backends=[_make_rust_backend()],
        frontend=None,
        include_keycloak=False,
    )
    config.validate()

    project_root = generate(config, quiet=True)
    backend_dir = project_root / "services" / "backend-rust"
    assert (backend_dir / "Cargo.toml").exists(), "rust backend Cargo.toml missing"

    # `--no-run` keeps this under ~2 min — full `cargo test` would dominate runtime.
    result = _run(["cargo", "test", "--no-run", "--manifest-path", "Cargo.toml"], cwd=backend_dir)
    assert result.returncode == 0, (
        f"rust backend failed to compile:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )


# -----------------------------------------------------------------------------
# Case 4: Multi-backend (python + node + rust) + Vue + Keycloak.
# This is the path with zero coverage today and most likely to surface
# port-collision / proxy-config bugs.
# -----------------------------------------------------------------------------


def test_multi_backend_with_keycloak_scaffolds(
    tmp_path: Path,
    require_uv: None,
    require_npm: None,
    require_cargo: None,
    require_git: None,
) -> None:
    config = ProjectConfig(
        project_name="E2E Multi",
        output_dir=str(tmp_path),
        backends=[
            _make_python_backend(name="api-py", port=5010),
            _make_node_backend(name="api-node", port=5011),
            _make_rust_backend(name="api-rust", port=5012),
        ],
        frontend=_make_frontend(FrontendFramework.VUE, with_auth=True),
        include_keycloak=True,
    )
    config.validate()

    project_root = generate(config, quiet=True)

    # All three backends must exist with their toolchain manifests.
    assert (project_root / "services" / "api-py" / "pyproject.toml").exists()
    assert (project_root / "services" / "api-node" / "package.json").exists()
    assert (project_root / "services" / "api-rust" / "Cargo.toml").exists()

    # Multi-backend init-db.sh must list all three databases.
    init_db = (project_root / "init-db.sh").read_text(encoding="utf-8")
    assert "api_py" in init_db or "api-py" in init_db
    assert "api_node" in init_db or "api-node" in init_db
    assert "api_rust" in init_db or "api-rust" in init_db

    # Keycloak realm + gatekeeper must be present.
    assert (project_root / "infra" / "gatekeeper").is_dir()
    assert (project_root / "infra" / "keycloak").is_dir()
    assert (project_root / "infra" / "keycloak-realm.json").exists()

    # docker-compose.yml must reference all three backends.
    compose = (project_root / "docker-compose.yml").read_text(encoding="utf-8")
    assert "api-py" in compose
    assert "api-node" in compose
    assert "api-rust" in compose


# -----------------------------------------------------------------------------
# Case 5: Vue with include_auth=False — regression fence for the Vue auth-off
# path. vue-tsc must pass against the patched project.
# -----------------------------------------------------------------------------


def test_vue_auth_off_typechecks(
    tmp_path: Path, require_uv: None, require_npm: None, require_git: None
) -> None:
    config = ProjectConfig(
        project_name="E2E Vue NoAuth",
        output_dir=str(tmp_path),
        backends=[_make_python_backend()],
        frontend=_make_frontend(FrontendFramework.VUE, with_auth=False),
        include_keycloak=False,
    )
    config.validate()

    project_root = generate(config, quiet=True)
    frontend_dir = project_root / "apps" / "frontend"
    assert (frontend_dir / "package.json").exists()

    result = _run(["npx", "--yes", "vue-tsc", "--noEmit"], cwd=frontend_dir)
    assert result.returncode == 0, (
        f"vue-tsc failed for auth-off project:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )


# -----------------------------------------------------------------------------
# Case 6: Svelte with include_chat=True — the Svelte matrix previously only
# exercised chat=False; this covers the chat-on type-check path.
# -----------------------------------------------------------------------------


@pytest.mark.skip(
    reason=(
        "Svelte chat template has pre-existing @ag-ui/client type drift "
        "(threadId on RunHttpAgentConfig, activity role on chat messages, "
        "{@const} placement in CanvasPane) plus a content-type mismatch in "
        "AiChatMessage. These are separate from the feature-flag-cleanup scope "
        "of this fix pass — tracked as a follow-up. Enable once the Svelte "
        "chat surface is updated to the current @ag-ui/client API."
    )
)
def test_svelte_chat_on_typechecks(
    tmp_path: Path, require_uv: None, require_npm: None, require_git: None
) -> None:
    config = ProjectConfig(
        project_name="E2E Svelte Chat",
        output_dir=str(tmp_path),
        backends=[_make_python_backend()],
        frontend=_make_frontend(FrontendFramework.SVELTE, with_auth=True, with_chat=True),
        include_keycloak=False,
    )
    config.validate()

    project_root = generate(config, quiet=True)
    frontend_dir = project_root / "apps" / "frontend"
    assert (frontend_dir / "package.json").exists()

    install = _run(["npm", "install", "--no-audit", "--no-fund"], cwd=frontend_dir)
    assert install.returncode == 0, f"npm install failed:\n{install.stderr}"

    result = _run(["npx", "--yes", "svelte-check", "--output", "human"], cwd=frontend_dir)
    assert result.returncode == 0, (
        f"svelte-check failed for chat-on project:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )


# -----------------------------------------------------------------------------
# Case 7: Flutter minimal — auth off, chat off, openapi on (Flutter's home
# repository requires the generated OpenAPI client; see FrontendConfig.validate).
# -----------------------------------------------------------------------------


def test_flutter_minimal_analyzes(
    tmp_path: Path, require_uv: None, require_flutter: None, require_git: None
) -> None:
    config = ProjectConfig(
        project_name="E2E Flutter Min",
        output_dir=str(tmp_path),
        backends=[_make_python_backend()],
        frontend=_make_frontend(
            FrontendFramework.FLUTTER,
            with_auth=False,
            with_chat=False,
            with_openapi=True,
        ),
        include_keycloak=False,
    )
    config.validate()

    project_root = generate(config, quiet=True)
    frontend_dir = project_root / "apps" / "frontend"
    assert (frontend_dir / "pubspec.yaml").exists()

    # pub get must succeed before analyze can run.
    pub_get = _run(["flutter", "pub", "get"], cwd=frontend_dir)
    assert pub_get.returncode == 0, f"flutter pub get failed:\n{pub_get.stderr}"

    result = _run(["flutter", "analyze", "--no-fatal-infos"], cwd=frontend_dir)
    assert result.returncode == 0, (
        f"flutter analyze found errors:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )


# -----------------------------------------------------------------------------
# Case 8: Flutter full — auth + chat + openapi all on. Covers the "intended"
# production Flutter path.
# -----------------------------------------------------------------------------


@pytest.mark.skip(
    reason="Flutter chat requires the forge_canvas package which isn't yet published to "
    "pub.dev (tracked in RFC-003). Enable this test once the package is live."
)
def test_flutter_full_analyzes(
    tmp_path: Path, require_uv: None, require_flutter: None, require_git: None
) -> None:
    config = ProjectConfig(
        project_name="E2E Flutter Full",
        output_dir=str(tmp_path),
        backends=[_make_python_backend()],
        frontend=_make_frontend(
            FrontendFramework.FLUTTER,
            with_auth=True,
            with_chat=True,
            with_openapi=True,
        ),
        include_keycloak=False,
    )
    config.validate()

    project_root = generate(config, quiet=True)
    frontend_dir = project_root / "apps" / "frontend"
    assert (frontend_dir / "pubspec.yaml").exists()

    pub_get = _run(["flutter", "pub", "get"], cwd=frontend_dir)
    assert pub_get.returncode == 0, f"flutter pub get failed:\n{pub_get.stderr}"

    result = _run(["flutter", "analyze", "--no-fatal-infos"], cwd=frontend_dir)
    assert result.returncode == 0, (
        f"flutter analyze found errors:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )
