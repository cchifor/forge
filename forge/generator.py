"""Copier orchestration -- generates all project components."""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path

from copier import run_copy

from forge import variable_mapper
from forge.config import BackendLanguage, FrontendFramework, ProjectConfig
from forge.docker_manager import render_compose, render_frontend_dockerfile, render_keycloak_realm, render_nginx_conf
from forge.e2e_templates import (
    generate_e2e_auth_conftest,
    generate_e2e_auth_tests,
    generate_e2e_conftest,
    generate_e2e_test,
)

TEMPLATES_DIR = Path(__file__).parent / "templates"

TEMPLATE_DIRS = {
    "backend": "python-service-template",
    FrontendFramework.VUE: "vue-frontend-template",
    FrontendFramework.SVELTE: "svelte-frontend-template",
    FrontendFramework.FLUTTER: "flutter-frontend-template",
}


def generate(config: ProjectConfig, quiet: bool = False) -> Path:
    """Generate all project components and return the project root path."""
    project_root = Path(config.output_dir).resolve() / config.project_slug
    project_root.mkdir(parents=True, exist_ok=True)

    def _log(msg: str) -> None:
        if not quiet:
            print(msg)

    # 1. Generate backend
    if config.backend:
        if config.backend.language == BackendLanguage.NODE:
            _log("  Generating Node.js backend ...")
            backend_dir = _generate_node_backend(config, project_root, quiet=quiet)
            if not quiet:
                print("  Setting up Node.js backend ...")
                _setup_node_backend(backend_dir)
        elif config.backend.language == BackendLanguage.RUST:
            _log("  Generating Rust backend ...")
            backend_dir = _generate_rust_backend(config, project_root, quiet=quiet)
            if not quiet:
                print("  Setting up Rust backend ...")
                _setup_rust_backend(backend_dir)
        else:
            _log("  Generating Python backend ...")
            backend_dir = _generate_backend(config, project_root, quiet=quiet)
            if not quiet:
                print("  Setting up backend ...")
                _setup_backend(backend_dir)

    # 2. Generate frontend
    if config.frontend and config.frontend.framework != FrontendFramework.NONE:
        _log(f"  Generating {config.frontend.framework.value} frontend ...")
        _generate_frontend(config, project_root, quiet=quiet)

    # 3. Render Docker Compose
    if config.backend:
        _log("  Rendering docker-compose.yml ...")
        render_compose(config, project_root)
        # Copy auth infrastructure if Keycloak is enabled
        if config.include_keycloak:
            # Write init-db.sh with explicit LF (CRLF breaks shebang in Linux)
            src = (TEMPLATES_DIR / "init-db.sh").read_text(encoding="utf-8")
            dst = project_root / "init-db.sh"
            dst.write_bytes(src.replace("\r\n", "\n").encode("utf-8"))
            # Render Keycloak realm JSON
            _log("  Rendering keycloak-realm.json ...")
            render_keycloak_realm(config, project_root)
            # Copy gatekeeper service
            _log("  Copying gatekeeper ...")
            gatekeeper_src = TEMPLATES_DIR / "gatekeeper"
            gatekeeper_dst = project_root / "gatekeeper"
            if gatekeeper_src.exists():
                shutil.copytree(str(gatekeeper_src), str(gatekeeper_dst), dirs_exist_ok=True)
            # Copy keycloak (Dockerfile + themes)
            _log("  Copying keycloak ...")
            keycloak_src = TEMPLATES_DIR / "keycloak"
            keycloak_dst = project_root / "keycloak"
            if keycloak_src.exists():
                shutil.copytree(str(keycloak_src), str(keycloak_dst), dirs_exist_ok=True)
            # Copy validate.sh (LF line endings for Linux containers)
            validate_src = (TEMPLATES_DIR / "validate.sh").read_text(encoding="utf-8")
            validate_dst = project_root / "validate.sh"
            validate_dst.write_bytes(validate_src.replace("\r\n", "\n").encode("utf-8"))

    # 4. Generate Playwright e2e tests
    if (
        config.frontend
        and config.frontend.framework != FrontendFramework.NONE
        and config.frontend.generate_e2e_tests
    ):
        _log("  Generating Playwright e2e tests ...")
        _generate_e2e_tests(config, project_root)

    # 5. Render frontend Dockerfile and nginx.conf (all frameworks)
    if config.frontend and config.frontend.framework != FrontendFramework.NONE:
        _log("  Rendering frontend Dockerfile ...")
        frontend_dir = project_root / config.frontend_slug
        render_frontend_dockerfile(config, frontend_dir)
        render_nginx_conf(config, frontend_dir)

    # 6. Clean up per-template .git repos and create unified one
    _log("  Initializing git repository ...")
    _cleanup_sub_git_repos(project_root)
    _git_init(project_root)

    return project_root


def _make_feature_context(plural_name: str) -> dict[str, str]:
    """Derive all naming variants from a plural feature name."""
    singular = (
        plural_name.rstrip("s")
        if plural_name.endswith("s") and len(plural_name) > 1
        else plural_name
    )
    return {
        "plural": plural_name,
        "singular": singular,
        "Plural": plural_name[0].upper() + plural_name[1:],
        "Singular": singular[0].upper() + singular[1:],
    }


def _generate_e2e_tests(config: ProjectConfig, project_root: Path) -> None:
    """Generate Playwright e2e test files for each frontend feature."""
    e2e_dir = project_root / "tests" / "e2e"
    e2e_dir.mkdir(parents=True, exist_ok=True)

    # Write conftest.py -- use auth-enhanced version when Keycloak enabled
    conftest_path = e2e_dir / "conftest.py"
    if config.include_keycloak:
        conftest_path.write_text(generate_e2e_auth_conftest(), encoding="utf-8")
    else:
        conftest_path.write_text(generate_e2e_conftest(), encoding="utf-8")

    # Write auth flow tests when Keycloak enabled
    if config.include_keycloak:
        auth_test_path = e2e_dir / "test_auth.py"
        auth_test_path.write_text(generate_e2e_auth_tests(), encoding="utf-8")

    # Write per-feature test files
    for feature_name in config.frontend.features:
        ctx = _make_feature_context(feature_name)
        test_content = generate_e2e_test(ctx)
        test_path = e2e_dir / f"test_{feature_name}.py"
        test_path.write_text(test_content, encoding="utf-8")


def _generate_backend(config: ProjectConfig, project_root: Path, quiet: bool = False) -> Path:
    """Generate backend using Copier (_subdirectory: template)."""
    ctx = variable_mapper.backend_context(config)
    dst = project_root / config.backend_slug
    dst.mkdir(exist_ok=True)
    run_copy(
        src_path=str(TEMPLATES_DIR / TEMPLATE_DIRS["backend"]),
        dst_path=str(dst),
        data=ctx,
        unsafe=True,
        defaults=True,
        overwrite=True,
        quiet=quiet,
    )
    return dst


def _generate_node_backend(config: ProjectConfig, project_root: Path, quiet: bool = False) -> Path:
    """Generate Node.js backend using Copier."""
    ctx = variable_mapper.node_backend_context(config)
    dst = project_root / config.backend_slug
    dst.mkdir(exist_ok=True)
    template_path = TEMPLATES_DIR / "node-service-template"
    if not template_path.exists():
        raise FileNotFoundError(f"Node.js template not found at {template_path}")
    run_copy(
        src_path=str(template_path),
        dst_path=str(dst),
        data=ctx,
        unsafe=True,
        defaults=True,
        overwrite=True,
        quiet=quiet,
    )
    return dst


def _generate_rust_backend(config: ProjectConfig, project_root: Path, quiet: bool = False) -> Path:
    """Generate Rust backend using Copier."""
    ctx = variable_mapper.rust_backend_context(config)
    dst = project_root / config.backend_slug
    dst.mkdir(exist_ok=True)
    template_path = TEMPLATES_DIR / "rust-service-template"
    if not template_path.exists():
        raise FileNotFoundError(f"Rust template not found at {template_path}")
    run_copy(
        src_path=str(template_path),
        dst_path=str(dst),
        data=ctx,
        unsafe=True,
        defaults=True,
        overwrite=True,
        quiet=quiet,
    )
    return dst


def _setup_rust_backend(backend_dir: Path) -> None:
    """Build, lint, and test the generated Rust backend."""
    _run_backend_cmd(backend_dir, ["cargo", "build"], "Build")
    _run_backend_cmd(backend_dir, ["cargo", "fmt", "--check"], "Format check")
    _run_backend_cmd(backend_dir, ["cargo", "clippy", "--all-targets", "--", "-D", "warnings"], "Lint")
    _run_backend_cmd(backend_dir, ["cargo", "test"], "Tests")


def _setup_node_backend(backend_dir: Path) -> None:
    """Install deps, lint, type check, and test the generated Node.js backend."""
    _run_backend_cmd(backend_dir, ["npm", "install"], "Install dependencies")
    _run_backend_cmd(backend_dir, ["npx", "biome", "check", "src/"], "Lint check")
    _run_backend_cmd(backend_dir, ["npx", "tsc", "--noEmit"], "Type check")
    _run_backend_cmd(backend_dir, ["npx", "vitest", "run"], "Tests")


def _generate_frontend(config: ProjectConfig, project_root: Path, quiet: bool = False) -> Path:
    """Generate frontend using Copier."""
    fw = config.frontend.framework
    template_dir = TEMPLATE_DIRS.get(fw)
    if template_dir is None:
        raise ValueError(f"No template for framework: {fw}")

    ctx = variable_mapper.frontend_context(config)

    if fw == FrontendFramework.FLUTTER:
        # Flutter template has no _subdirectory; it creates {{project_slug}}/
        # inside dst_path, so pass the project root directly.
        run_copy(
            src_path=str(TEMPLATES_DIR / template_dir),
            dst_path=str(project_root),
            data=ctx,
            unsafe=True,
            defaults=True,
            overwrite=True,
            quiet=quiet,
        )
    else:
        # Vue/Svelte use _subdirectory: template, generating INTO dst_path.
        dst = project_root / config.frontend_slug
        dst.mkdir(exist_ok=True)
        run_copy(
            src_path=str(TEMPLATES_DIR / template_dir),
            dst_path=str(dst),
            data=ctx,
            unsafe=True,
            defaults=True,
            overwrite=True,
            quiet=quiet,
        )

    return project_root / config.frontend_slug


def _run_backend_cmd(backend_dir: Path, cmd: list[str], description: str) -> bool:
    """Run a command in the backend directory, printing status."""
    try:
        result = subprocess.run(
            cmd,
            cwd=str(backend_dir),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=300,
        )
    except subprocess.TimeoutExpired:
        print(f"  [!!] {description} timed out (5m)")
        return False
    if result.returncode == 0:
        print(f"  [ok] {description}")
        return True
    else:
        print(f"  [!!] {description} failed")
        if result.stderr:
            for line in result.stderr.strip().splitlines()[-5:]:
                print(f"       {line}")
        return False


def _setup_backend(backend_dir: Path) -> None:
    """Install deps, run linting, and run tests for the generated backend."""
    _run_backend_cmd(backend_dir, ["uv", "sync"], "Install dependencies")
    _run_backend_cmd(backend_dir, ["uv", "run", "ruff", "check", "--fix", "src/", "tests/"], "Lint fix")
    _run_backend_cmd(backend_dir, ["uv", "run", "ruff", "format", "src/", "tests/"], "Format")
    _run_backend_cmd(backend_dir, ["uv", "run", "ty", "check", "src/"], "Type check")
    _run_backend_cmd(backend_dir, ["uv", "run", "pytest", "-v"], "Tests")


def _force_remove_readonly(func, path, _exc_info):
    """Error handler for shutil.rmtree to clear read-only flags on Windows."""
    os.chmod(path, stat.S_IWRITE)
    func(path)


def _cleanup_sub_git_repos(project_root: Path) -> None:
    """Remove .git directories from generated subdirectories."""
    for child in project_root.iterdir():
        if child.is_dir():
            git_dir = child / ".git"
            if git_dir.exists():
                shutil.rmtree(git_dir, onerror=_force_remove_readonly)


def _git_init(project_root: Path) -> None:
    """Initialize a single git repo at the project root."""
    # Provide author identity via env so git commit never prompts.
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "forge",
        "GIT_AUTHOR_EMAIL": "forge@localhost",
        "GIT_COMMITTER_NAME": "forge",
        "GIT_COMMITTER_EMAIL": "forge@localhost",
    }
    subprocess.run(
        ["git", "init"],
        cwd=str(project_root),
        capture_output=True,
        timeout=30,
    )
    subprocess.run(
        ["git", "add", "."],
        cwd=str(project_root),
        capture_output=True,
        timeout=30,
    )
    subprocess.run(
        ["git", "commit", "-m", "Initial commit from forge"],
        cwd=str(project_root),
        capture_output=True,
        timeout=30,
        env=env,
    )
