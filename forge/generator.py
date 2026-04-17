"""Copier orchestration -- generates all project components."""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

from copier import run_copy

from forge import variable_mapper
from forge.config import (
    BACKEND_REGISTRY,
    BackendConfig,
    BackendLanguage,
    FrontendFramework,
    ProjectConfig,
)
from forge.docker_manager import (
    render_compose,
    render_frontend_dockerfile,
    render_init_db,
    render_keycloak_realm,
    render_nginx_conf,
)

TEMPLATES_DIR = Path(__file__).parent / "templates"

TEMPLATE_DIRS = {
    "backend": "services/python-service-template",
    "e2e": "tests/e2e-testing-template",
    FrontendFramework.VUE: "apps/vue-frontend-template",
    FrontendFramework.SVELTE: "apps/svelte-frontend-template",
    FrontendFramework.FLUTTER: "apps/flutter-frontend-template",
}


class GeneratorError(RuntimeError):
    """Raised when a step required to produce a usable project fails.

    Callers (CLI main) catch this and surface it as a clean error message
    or a JSON error envelope, instead of leaking a stack trace.
    """


def generate(config: ProjectConfig, quiet: bool = False) -> Path:
    """Generate all project components and return the project root path."""
    project_root = Path(config.output_dir).resolve() / config.project_slug
    project_root.mkdir(parents=True, exist_ok=True)

    def _log(msg: str) -> None:
        if not quiet:
            print(msg)

    # 1. Generate backends — dispatch driven by config.BACKEND_REGISTRY.
    backend_setup: dict[BackendLanguage, Callable[[Path], None]] = {
        BackendLanguage.PYTHON: _setup_backend,
        BackendLanguage.NODE: _setup_node_backend,
        BackendLanguage.RUST: _setup_rust_backend,
    }
    for bc in config.backends:
        spec = BACKEND_REGISTRY[bc.language]
        backend_dir = project_root / "services" / bc.name
        _log(f"  Generating {spec.display_label} backend '{bc.name}' ...")
        _generate_single_backend(bc, spec.template_dir, backend_dir, quiet)
        # Node always installs deps to create the lockfile Docker builds depend on.
        if bc.language == BackendLanguage.NODE:
            _run_backend_cmd(backend_dir, ["npm", "install"], "Install dependencies", required=True)
        if not quiet:
            backend_setup[bc.language](backend_dir)

    # 2. Generate frontend
    if config.frontend and config.frontend.framework != FrontendFramework.NONE:
        _log(f"  Generating {config.frontend.framework.value} frontend ...")
        _generate_frontend(config, project_root, quiet=quiet)

    # 3. Render Docker Compose
    if config.backends:
        _log("  Rendering docker-compose.yml ...")
        render_compose(config, project_root)
        # Render init-db.sh (creates databases for all backends)
        if len(config.backends) > 1 or config.include_keycloak:
            _log("  Rendering init-db.sh ...")
            render_init_db(config, project_root)
        # Copy auth infrastructure if Keycloak is enabled
        if config.include_keycloak:
            # Render Keycloak realm JSON
            _log("  Rendering keycloak-realm.json ...")
            render_keycloak_realm(config, project_root)
            # Copy gatekeeper service
            _log("  Copying gatekeeper ...")
            gatekeeper_src = TEMPLATES_DIR / "infra" / "gatekeeper"
            gatekeeper_dst = project_root / "infra" / "gatekeeper"
            if gatekeeper_src.exists():
                shutil.copytree(str(gatekeeper_src), str(gatekeeper_dst), dirs_exist_ok=True)
            # Copy keycloak (Dockerfile + themes)
            _log("  Copying keycloak ...")
            keycloak_src = TEMPLATES_DIR / "infra" / "keycloak"
            keycloak_dst = project_root / "infra" / "keycloak"
            if keycloak_src.exists():
                shutil.copytree(str(keycloak_src), str(keycloak_dst), dirs_exist_ok=True)
            # Copy validate.sh (LF line endings for Linux containers)
            validate_src = (TEMPLATES_DIR / "infra" / "validate.sh").read_text(encoding="utf-8")
            validate_dst = project_root / "validate.sh"
            validate_dst.write_bytes(validate_src.replace("\r\n", "\n").encode("utf-8"))

    # 4. Generate Playwright e2e tests
    if (
        config.frontend
        and config.frontend.framework != FrontendFramework.NONE
        and config.frontend.generate_e2e_tests
    ):
        _log("  Generating Playwright e2e tests ...")
        _generate_e2e_tests(config, project_root, quiet=quiet)

    # 5. Render frontend Dockerfile and nginx.conf (all frameworks)
    if config.frontend and config.frontend.framework != FrontendFramework.NONE:
        _log("  Rendering frontend Dockerfile ...")
        frontend_dir = project_root / "apps" / config.frontend_slug
        render_frontend_dockerfile(config, frontend_dir)
        render_nginx_conf(config, frontend_dir)

    # 6. Stamp forge metadata so the project can be re-generated / updated later.
    _write_forge_toml(config, project_root)

    # 7. Clean up per-template .git repos and create unified one
    _log("  Initializing git repository ...")
    _cleanup_sub_git_repos(project_root)
    _git_init(project_root)

    return project_root


def _write_forge_toml(config: ProjectConfig, project_root: Path) -> None:
    """Write a forge.toml manifest at the project root.

    Captures the forge version that scaffolded the project plus per-template paths.
    Lets `copier update` (or a future `forge update` subcommand) figure out what to
    re-render after a template change.
    """
    from importlib import metadata

    try:
        forge_version = metadata.version("forge")
    except metadata.PackageNotFoundError:
        forge_version = "0.0.0+unknown"

    languages_used = sorted({bc.language.value for bc in config.backends})
    template_lines = [
        f'  {lang} = "{BACKEND_REGISTRY[BackendLanguage(lang)].template_dir}"'
        for lang in languages_used
    ]
    if config.frontend and config.frontend.framework != FrontendFramework.NONE:
        fw = config.frontend.framework
        template_dir = TEMPLATE_DIRS.get(fw)
        if template_dir:
            template_lines.append(f'  {fw.value} = "{template_dir}"')

    content = (
        "# Generated by forge — do not edit by hand.\n"
        "# Re-render any subdirectory with `copier update` using its `.copier-answers.yml`.\n"
        "[forge]\n"
        f'version = "{forge_version}"\n'
        f'project_name = "{config.project_name}"\n'
        "\n"
        "[forge.templates]\n" + "\n".join(template_lines) + "\n"
    )
    (project_root / "forge.toml").write_text(content, encoding="utf-8")


def _run_copier(template_path: Path, dst_path: Path, data: dict[str, Any], quiet: bool) -> None:
    """Invoke Copier and translate its failures into GeneratorError.

    Raised errors include the template path so JSON-mode callers see a useful envelope
    instead of a raw Copier traceback.
    """
    if not template_path.exists():
        raise GeneratorError(f"Template not found: {template_path}")
    try:
        run_copy(
            src_path=str(template_path),
            dst_path=str(dst_path),
            data=data,
            unsafe=True,
            defaults=True,
            overwrite=True,
            quiet=quiet,
        )
    except GeneratorError:
        raise
    except Exception as e:  # Copier raises a variety of internal exception types
        raise GeneratorError(f"Copier failed for template '{template_path.name}': {e}") from e


def _generate_e2e_tests(config: ProjectConfig, project_root: Path, quiet: bool = False) -> Path:
    """Generate E2E testing platform using Copier template."""
    ctx = variable_mapper.e2e_context(config)
    dst = project_root / "tests" / "e2e"
    dst.mkdir(parents=True, exist_ok=True)
    _run_copier(TEMPLATES_DIR / "tests" / "e2e-testing-template", dst, ctx, quiet)
    return dst


def _generate_single_backend(
    bc: BackendConfig, template_name: str, dst: Path, quiet: bool = False
) -> Path:
    """Generate a single backend using Copier."""
    ctx = variable_mapper.backend_context(bc)
    dst.mkdir(parents=True, exist_ok=True)
    _run_copier(TEMPLATES_DIR / template_name, dst, ctx, quiet)
    return dst


def _setup_rust_backend(backend_dir: Path) -> None:
    """Build, lint, and test the generated Rust backend."""
    _run_backend_cmd(backend_dir, ["cargo", "build"], "Build")
    _run_backend_cmd(backend_dir, ["cargo", "fmt", "--check"], "Format check")
    _run_backend_cmd(
        backend_dir, ["cargo", "clippy", "--all-targets", "--", "-D", "warnings"], "Lint"
    )
    _run_backend_cmd(backend_dir, ["cargo", "test"], "Tests")


def _setup_node_backend(backend_dir: Path) -> None:
    """Lint, type check, and test the generated Node.js backend.
    Note: npm install already ran (always runs to create lockfile for Docker).
    """
    _run_backend_cmd(backend_dir, ["npx", "biome", "check", "src/"], "Lint check")
    _run_backend_cmd(backend_dir, ["npx", "tsc", "--noEmit"], "Type check")
    _run_backend_cmd(backend_dir, ["npx", "vitest", "run"], "Tests")


def _generate_frontend(config: ProjectConfig, project_root: Path, quiet: bool = False) -> Path:
    """Generate frontend using Copier."""
    if config.frontend is None:
        raise GeneratorError("_generate_frontend called without a frontend configured")
    fw = config.frontend.framework
    template_dir = TEMPLATE_DIRS.get(fw)
    if template_dir is None:
        raise GeneratorError(f"No template for framework: {fw}")

    ctx = variable_mapper.frontend_context(config)

    if fw == FrontendFramework.FLUTTER:
        # Flutter template has no _subdirectory; it creates {{project_slug}}/
        # inside dst_path, so pass the apps directory.
        dst = project_root / "apps"
    else:
        # Vue/Svelte use _subdirectory: template, generating INTO dst_path.
        dst = project_root / "apps" / config.frontend_slug
    dst.mkdir(parents=True, exist_ok=True)
    _run_copier(TEMPLATES_DIR / template_dir, dst, ctx, quiet)
    return project_root / "apps" / config.frontend_slug


def _run_backend_cmd(
    backend_dir: Path,
    cmd: list[str],
    description: str,
    *,
    required: bool = False,
) -> bool:
    """Run a command in the backend directory, printing status.

    When `required=True`, any failure (timeout, missing tool, non-zero exit) raises
    GeneratorError so the project isn't left in a half-built state. When
    `required=False` (default), failures are logged and skipped — appropriate for
    best-effort interactive setup steps like `cargo fmt --check` or `vitest run`.
    """
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
    except subprocess.TimeoutExpired as e:
        msg = f"{description} timed out (5m)"
        if required:
            raise GeneratorError(f"{msg} while running: {' '.join(cmd)}") from e
        print(f"  [!!] {msg}")
        return False
    except FileNotFoundError as e:
        msg = f"{description} skipped ({cmd[0]} not found)"
        if required:
            raise GeneratorError(
                f"required tool '{cmd[0]}' not found on PATH (needed for: {description})"
            ) from e
        print(f"  [!!] {msg}")
        return False
    if result.returncode == 0:
        print(f"  [ok] {description}")
        return True
    print(f"  [!!] {description} failed")
    stderr_tail = ""
    if result.stderr:
        stderr_tail = "\n".join(result.stderr.strip().splitlines()[-5:])
        for line in stderr_tail.splitlines():
            print(f"       {line}")
    if required:
        suffix = f"\n{stderr_tail}" if stderr_tail else ""
        raise GeneratorError(
            f"{description} failed (exit {result.returncode}): {' '.join(cmd)}{suffix}"
        )
    return False


def _setup_backend(backend_dir: Path) -> None:
    """Install deps, run linting, and run tests for the generated backend."""
    _run_backend_cmd(backend_dir, ["uv", "sync"], "Install dependencies")
    _run_backend_cmd(
        backend_dir, ["uv", "run", "ruff", "check", "--fix", "src/", "tests/"], "Lint fix"
    )
    _run_backend_cmd(backend_dir, ["uv", "run", "ruff", "format", "src/", "tests/"], "Format")
    _run_backend_cmd(backend_dir, ["uv", "run", "ty", "check", "src/"], "Type check")
    _run_backend_cmd(backend_dir, ["uv", "run", "pytest", "-v"], "Tests")


def _force_remove_readonly(func, path, _exc_info):
    """Error handler for shutil.rmtree to clear read-only flags on Windows."""
    os.chmod(path, stat.S_IWRITE)
    func(path)


def _cleanup_sub_git_repos(project_root: Path) -> None:
    """Remove .git directories from generated subdirectories (recursive)."""
    for git_dir in project_root.rglob(".git"):
        if git_dir.is_dir() and git_dir.parent != project_root:
            shutil.rmtree(git_dir, onerror=_force_remove_readonly)


def _git_init(project_root: Path) -> None:
    """Initialize a single git repo at the project root.

    Each git step (init, add, commit) is checked; a failure on any step raises
    GeneratorError so callers don't end up with a half-initialized repo or, worse,
    a 'success' return with no commit at all.
    """
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "forge",
        "GIT_AUTHOR_EMAIL": "forge@localhost",
        "GIT_COMMITTER_NAME": "forge",
        "GIT_COMMITTER_EMAIL": "forge@localhost",
    }
    for step, cmd, step_env in (
        ("init", ["git", "init"], None),
        ("add", ["git", "add", "."], None),
        ("commit", ["git", "commit", "-m", "Initial commit from forge"], env),
    ):
        try:
            subprocess.run(
                cmd,
                cwd=str(project_root),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
                check=True,
                env=step_env,
            )
        except FileNotFoundError as e:
            raise GeneratorError(
                "git executable not found on PATH; install git to scaffold a project"
            ) from e
        except subprocess.TimeoutExpired as e:
            raise GeneratorError(f"git {step} timed out after 30s") from e
        except subprocess.CalledProcessError as e:
            stderr_tail = ""
            if e.stderr:
                stderr_tail = "\n".join(str(e.stderr).strip().splitlines()[-5:])
            suffix = f"\n{stderr_tail}" if stderr_tail else ""
            raise GeneratorError(f"git {step} failed (exit {e.returncode}){suffix}") from e
