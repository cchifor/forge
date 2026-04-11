"""Docker Compose rendering and lifecycle management."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from forge.config import FrontendFramework, ProjectConfig

TEMPLATES_DIR = Path(__file__).parent / "templates"

BUILD_DIR = {
    FrontendFramework.VUE: "dist",
    FrontendFramework.SVELTE: "build",
}


# -- Rendering ----------------------------------------------------------------

def _jinja_env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        keep_trailing_newline=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )


def render_compose(config: ProjectConfig, project_root: Path) -> Path:
    """Render docker-compose.yml into the project root."""
    env = _jinja_env()
    template = env.get_template("docker-compose.yml.j2")

    has_frontend = (
        config.frontend is not None
        and config.frontend.framework != FrontendFramework.NONE
    )

    # Build per-backend context list for the template loop
    backends_ctx = []
    for bc in config.backends:
        backends_ctx.append({
            "name": bc.name,
            "language": bc.language.value,
            "port": bc.server_port,
            "db_name": bc.name.replace("-", "_"),
        })

    # Primary backend (first) for backward-compat references
    primary = config.backend

    context = {
        "project_slug": config.project_slug,
        "backends": backends_ctx,
        "backend_language": primary.language.value if primary else "python",
        "backend_slug": config.backend_slug,
        "backend_port": primary.server_port if primary else 5000,
        "db_name": config.backend_slug.replace("-", "_"),
        "has_frontend": has_frontend,
        "frontend_slug": config.frontend_slug if has_frontend else "",
        "frontend_port": (
            config.frontend.server_port if config.frontend and has_frontend else 5173
        ),
        "include_keycloak": config.include_keycloak,
        "keycloak_port": config.keycloak_port,
        "traefik_dashboard_port": 9090,
        "keycloak_realm": (
            config.frontend.keycloak_realm
            if config.frontend and config.include_keycloak
            and config.frontend.keycloak_realm != "master"
            else "app"  # matches Host(`app.localhost`) for Gatekeeper tenant extraction
        ),
        "keycloak_client_id": (
            config.frontend.keycloak_client_id
            if config.frontend and config.include_keycloak
            else config.frontend_slug
        ),
    }

    output = template.render(context)
    compose_path = project_root / "docker-compose.yml"
    compose_path.write_text(output, encoding="utf-8")
    return compose_path


def render_frontend_dockerfile(config: ProjectConfig, frontend_dir: Path) -> Path:
    """Render a two-stage production Dockerfile into the frontend directory."""
    env = _jinja_env()
    fc = config.frontend

    if fc.framework == FrontendFramework.FLUTTER:
        template = env.get_template("Dockerfile.flutter.j2")
        context = {}
    else:
        template = env.get_template("Dockerfile.node.j2")
        context = {
            "package_manager": fc.package_manager if fc else "npm",
            "build_dir": BUILD_DIR.get(fc.framework, "dist"),
        }

    output = template.render(context)
    dockerfile_path = frontend_dir / "Dockerfile"
    dockerfile_path.write_text(output, encoding="utf-8")
    return dockerfile_path


def render_keycloak_realm(config: ProjectConfig, project_root: Path) -> Path:
    """Render keycloak-realm.json into the project root."""
    env = _jinja_env()
    template = env.get_template("keycloak-realm.json.j2")

    fc = config.frontend
    context = {
        "project_name": config.project_name,
        "keycloak_realm": (
            fc.keycloak_realm
            if fc and fc.keycloak_realm and fc.keycloak_realm != "master"
            else "app"  # matches Host(`app.localhost`) for Gatekeeper tenant extraction
        ),
        "keycloak_client_id": (
            fc.keycloak_client_id if fc and fc.keycloak_client_id
            else config.project_slug
        ),
    }

    output = template.render(context)
    realm_path = project_root / "keycloak-realm.json"
    realm_path.write_text(output, encoding="utf-8")
    return realm_path


def render_init_db(config: ProjectConfig, project_root: Path) -> Path:
    """Render init-db.sh that creates databases for all backends + keycloak."""
    env = _jinja_env()
    template = env.get_template("init-db.sh.j2")

    # Collect all databases that need creating beyond the default POSTGRES_DB
    extra_dbs = set()
    for bc in config.backends:
        db_name = bc.name.replace("-", "_")
        extra_dbs.add(db_name)
    if config.include_keycloak:
        extra_dbs.add("keycloak")
    # Remove the primary db (created by POSTGRES_DB env var)
    primary_db = config.backend_slug.replace("-", "_") if config.backends else "backend"
    extra_dbs.discard(primary_db)

    output = template.render({"extra_databases": sorted(extra_dbs)})
    init_path = project_root / "init-db.sh"
    # Write with LF line endings (CRLF breaks shebang in Linux containers)
    init_path.write_bytes(output.replace("\r\n", "\n").encode("utf-8"))
    return init_path


def render_nginx_conf(config: ProjectConfig, frontend_dir: Path) -> Path:
    """Render nginx.conf into the frontend directory (static files + SPA fallback only)."""
    env = _jinja_env()
    template = env.get_template("nginx.conf.j2")
    output = template.render({})
    nginx_path = frontend_dir / "nginx.conf"
    nginx_path.write_text(output, encoding="utf-8")
    return nginx_path


# -- Lifecycle ----------------------------------------------------------------

def _docker_running() -> bool:
    """Check if the Docker daemon is reachable."""
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            timeout=10,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def boot(project_root: Path) -> None:
    """Run docker compose up --build with error handling."""
    compose_file = project_root / "docker-compose.yml"
    if not compose_file.exists():
        print("  Error: docker-compose.yml not found.")
        return

    if not _docker_running():
        print("  Error: Docker is not running.")
        print("  Please start Docker Desktop and try again:")
        print(f"    cd {project_root}")
        print("    docker compose up --build")
        return

    print("  Starting Docker Compose stack ...")
    print("  (Press Ctrl+C to stop)\n")
    try:
        subprocess.run(
            ["docker", "compose", "up", "--build"],
            cwd=str(project_root),
            check=True,
        )
    except subprocess.CalledProcessError:
        print("\n  Docker Compose failed. Cleaning up ...")
        teardown(project_root)
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n\n  Interrupted. Cleaning up ...")
        teardown(project_root)


def teardown(project_root: Path) -> None:
    """Run docker compose down to clean up containers."""
    subprocess.run(
        ["docker", "compose", "down", "--volumes", "--remove-orphans"],
        cwd=str(project_root),
        capture_output=True,
    )
    print("  Stack stopped and cleaned up.")
