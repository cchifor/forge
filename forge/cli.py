"""CLI entry point for forge-cli. Supports interactive and headless modes."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import questionary

from forge.config import (
    BackendConfig,
    FrontendConfig,
    FrontendFramework,
    ProjectConfig,
    validate_features,
)
from forge.docker_manager import boot
from forge.generator import generate


# -- Argument parsing ---------------------------------------------------------

FRAMEWORK_MAP = {
    "vue": FrontendFramework.VUE,
    "svelte": FrontendFramework.SVELTE,
    "flutter": FrontendFramework.FLUTTER,
    "none": FrontendFramework.NONE,
}

COLOR_SCHEMES = ["blue", "indigo", "teal", "green", "deepPurple", "red", "amber", "cyan"]


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="forge", description="Project Generator")

    # Config file (YAML or JSON, use - for stdin)
    p.add_argument("--config", "-c", type=str, metavar="FILE",
                    help="YAML/JSON config file (use - for stdin)")

    # Project
    p.add_argument("--project-name", metavar="NAME")
    p.add_argument("--description", metavar="DESC")
    p.add_argument("--output-dir", metavar="DIR", default=".")

    # Backend
    p.add_argument("--backend-port", type=int, metavar="PORT")
    p.add_argument("--python-version", choices=["3.13", "3.12", "3.11"])

    # Frontend
    p.add_argument("--frontend", choices=list(FRAMEWORK_MAP.keys()),
                    metavar="FRAMEWORK")
    p.add_argument("--features", metavar="LIST",
                    help="Comma-separated CRUD entities")
    p.add_argument("--author-name", metavar="NAME")
    p.add_argument("--package-manager", choices=["npm", "pnpm", "yarn", "bun"])
    p.add_argument("--frontend-port", type=int, metavar="PORT")
    p.add_argument("--color-scheme", choices=COLOR_SCHEMES)
    p.add_argument("--org-name", metavar="ORG",
                    help="Flutter org in reverse domain (e.g. com.example)")

    # Feature toggles
    p.add_argument("--include-auth", action="store_true", default=None)
    p.add_argument("--no-auth", dest="include_auth", action="store_false")
    p.add_argument("--include-chat", action="store_true", default=None)
    p.add_argument("--include-openapi", action="store_true", default=None)

    # Keycloak
    p.add_argument("--keycloak-port", type=int, metavar="PORT")
    p.add_argument("--keycloak-realm", metavar="REALM")
    p.add_argument("--keycloak-client-id", metavar="ID")

    # Behavior
    p.add_argument("--yes", "-y", action="store_true",
                    help="Skip confirmation prompts")
    p.add_argument("--no-docker", action="store_true",
                    help="Skip Docker Compose boot")

    return p.parse_args()


def _is_headless(args: argparse.Namespace) -> bool:
    """Return True if any CLI flag or config file was provided."""
    return (
        args.config is not None
        or args.project_name is not None
        or args.frontend is not None
        or args.yes
    )


# -- Config file loading ------------------------------------------------------

def _load_config_file(path_str: str) -> dict[str, Any]:
    """Load YAML or JSON config. Use '-' for stdin."""
    try:
        import yaml
        has_yaml = True
    except ImportError:
        has_yaml = False

    if path_str == "-":
        raw = sys.stdin.read()
        if has_yaml:
            return yaml.safe_load(raw) or {}
        return json.loads(raw)

    p = Path(path_str)
    if not p.exists():
        print(f"  Error: config file not found: {p}")
        sys.exit(2)

    text = p.read_text(encoding="utf-8")
    if p.suffix in (".yml", ".yaml") and has_yaml:
        return yaml.safe_load(text) or {}
    return json.loads(text)


# -- Build config from args/file ---------------------------------------------

def _get(args: argparse.Namespace, flag: str, cfg: dict, *keys: str, default=None):
    """Resolve a value: CLI flag > config file > default."""
    val = getattr(args, flag, None)
    if val is not None:
        return val
    d = cfg
    for k in keys:
        if isinstance(d, dict):
            d = d.get(k)
        else:
            return default
    return d if d is not None else default


def _build_config(args: argparse.Namespace, cfg: dict) -> ProjectConfig:
    """Build ProjectConfig from CLI args merged with config file."""
    project_name = _get(args, "project_name", cfg, "project_name", default="My Platform")
    description = _get(args, "description", cfg, "description", default="A full-stack application")
    output_dir = args.output_dir

    # Backend
    backend = BackendConfig(
        project_name=project_name,
        description=description,
        python_version=_get(args, "python_version", cfg, "backend", "python_version", default="3.13"),
        server_port=_get(args, "backend_port", cfg, "backend", "server_port", default=5000),
    )

    # Frontend
    fw_str = _get(args, "frontend", cfg, "frontend", "framework", default="none")
    framework = FRAMEWORK_MAP.get(fw_str, FrontendFramework.NONE)

    frontend = None
    include_auth = False

    if framework != FrontendFramework.NONE:
        features_raw = _get(args, "features", cfg, "frontend", "features", default="items")
        features = [f.strip() for f in features_raw.split(",") if f.strip()]
        include_auth = _get(args, "include_auth", cfg, "frontend", "include_auth", default=True)

        frontend = FrontendConfig(
            framework=framework,
            project_name=project_name,
            description=description,
            features=features,
            author_name=_get(args, "author_name", cfg, "frontend", "author_name", default="Your Name"),
            package_manager=_get(args, "package_manager", cfg, "frontend", "package_manager", default="npm"),
            include_auth=include_auth,
            include_chat=_get(args, "include_chat", cfg, "frontend", "include_chat", default=False),
            include_openapi=_get(args, "include_openapi", cfg, "frontend", "include_openapi", default=False),
            server_port=_get(args, "frontend_port", cfg, "frontend", "server_port", default=5173),
            default_color_scheme=_get(args, "color_scheme", cfg, "frontend", "default_color_scheme", default="blue"),
            org_name=_get(args, "org_name", cfg, "frontend", "org_name", default="com.example"),
        )

    # Keycloak
    include_keycloak = include_auth
    keycloak_port = _get(args, "keycloak_port", cfg, "keycloak", "port", default=8080)
    kc_realm = _get(args, "keycloak_realm", cfg, "keycloak", "realm", default="master")
    kc_client_id = _get(
        args, "keycloak_client_id", cfg, "keycloak", "client_id",
        default=project_name.lower().replace(" ", "-").replace("_", "-"),
    )

    if frontend and include_keycloak:
        frontend.keycloak_url = f"http://localhost:{keycloak_port}"
        frontend.keycloak_realm = kc_realm
        frontend.keycloak_client_id = kc_client_id

    return ProjectConfig(
        project_name=project_name,
        output_dir=str(output_dir),
        backend=backend,
        frontend=frontend,
        include_keycloak=include_keycloak,
        keycloak_port=keycloak_port,
    )


# -- Interactive prompt helpers -----------------------------------------------

def _ask_text(message: str, default: str = "") -> str:
    value = questionary.text(message, default=default).ask()
    if value is None:
        sys.exit(1)
    return value


def _ask_confirm(message: str, default: bool = True) -> bool:
    value = questionary.confirm(message, default=default).ask()
    if value is None:
        sys.exit(1)
    return value


def _ask_select(message: str, choices: list[str]) -> str:
    value = questionary.select(message, choices=choices).ask()
    if value is None:
        sys.exit(1)
    return value


def _parse_features(raw: str) -> list[str]:
    return [f.strip() for f in raw.split(",") if f.strip()]


def _ask_features() -> list[str]:
    while True:
        raw = _ask_text(
            "CRUD entities to generate (comma-separated, e.g. items, orders):",
            default="items",
        )
        features = _parse_features(raw)
        if not features:
            print("  Please enter at least one feature.")
            continue
        try:
            validate_features(features)
        except ValueError as e:
            print(f"  Invalid: {e}")
            continue
        return features


def _ask_port(message: str, default: str) -> int:
    while True:
        raw = _ask_text(message, default=default)
        try:
            port = int(raw)
            if not (1024 <= port <= 65535):
                raise ValueError
            return port
        except ValueError:
            print("  Port must be a number between 1024 and 65535.")


# -- Interactive flow ---------------------------------------------------------

def _collect_inputs() -> ProjectConfig | None:
    print()
    print("  +===================================+")
    print("  |             forge                  |")
    print("  |      Project Generator             |")
    print("  +===================================+")
    print()

    project_name = _ask_text("Project name:", default="My Platform")
    description = _ask_text("Description:", default="A full-stack application")

    print()
    print("  -- Backend (Python / FastAPI) --")
    backend_port = _ask_port("Backend server port:", default="5000")
    python_version = _ask_select(
        "Python version:", choices=["3.13", "3.12", "3.11"]
    )

    backend = BackendConfig(
        project_name=project_name,
        description=description,
        python_version=python_version,
        server_port=backend_port,
    )

    print()
    print("  -- Frontend --")
    fw_choice = _ask_select(
        "Frontend framework:",
        choices=["Vue 3", "Svelte 5", "Flutter", "None"],
    )
    fw_map = {
        "Vue 3": FrontendFramework.VUE,
        "Svelte 5": FrontendFramework.SVELTE,
        "Flutter": FrontendFramework.FLUTTER,
        "None": FrontendFramework.NONE,
    }
    framework = fw_map[fw_choice]

    frontend: FrontendConfig | None = None
    include_auth = False

    if framework != FrontendFramework.NONE:
        author_name = _ask_text("Author name:", default="Your Name")
        features = _ask_features()

        pkg_choices = {
            FrontendFramework.VUE: ["npm", "pnpm", "yarn"],
            FrontendFramework.SVELTE: ["npm", "pnpm", "bun"],
            FrontendFramework.FLUTTER: [],
        }
        pkg_manager = "npm"
        choices = pkg_choices.get(framework, [])
        if choices:
            pkg_manager = _ask_select("Package manager:", choices=choices)

        fe_port = 5173
        if framework != FrontendFramework.FLUTTER:
            fe_port = _ask_port("Frontend server port:", default="5173")

        include_auth = _ask_confirm("Enable Keycloak authentication?", default=True)
        include_chat = _ask_confirm("Enable AI chat panel?", default=False)
        include_openapi = False
        if framework in (FrontendFramework.VUE, FrontendFramework.FLUTTER):
            include_openapi = _ask_confirm(
                "Enable OpenAPI code generation?", default=False
            )

        color_scheme = "blue"
        if framework == FrontendFramework.VUE:
            color_scheme = _ask_select(
                "Default color scheme:", choices=COLOR_SCHEMES,
            )

        org_name = "com.example"
        if framework == FrontendFramework.FLUTTER:
            org_name = _ask_text(
                "Organization name (reverse domain):", default="com.example"
            )

        frontend = FrontendConfig(
            framework=framework,
            project_name=project_name,
            description=description,
            features=features,
            author_name=author_name,
            package_manager=pkg_manager,
            include_auth=include_auth,
            include_chat=include_chat,
            include_openapi=include_openapi,
            server_port=fe_port,
            default_color_scheme=color_scheme,
            org_name=org_name,
        )

    include_keycloak = include_auth
    keycloak_port = 8080
    kc_url = "http://localhost:8080"
    kc_realm = "master"
    kc_client_id = ""

    if include_keycloak:
        print()
        print("  -- Keycloak --")
        keycloak_port = _ask_port("Keycloak host port:", default="8080")
        kc_url = f"http://localhost:{keycloak_port}"
        kc_realm = _ask_text("Keycloak realm:", default="master")
        kc_client_id = _ask_text(
            "Keycloak client ID:",
            default=project_name.lower().replace(" ", "-").replace("_", "-"),
        )

    if frontend and include_keycloak:
        frontend.keycloak_url = kc_url
        frontend.keycloak_realm = kc_realm
        frontend.keycloak_client_id = kc_client_id

    config = ProjectConfig(
        project_name=project_name,
        backend=backend,
        frontend=frontend,
        include_keycloak=include_keycloak,
        keycloak_port=keycloak_port,
    )

    _print_summary(config)

    if not _ask_confirm("Proceed with generation?"):
        return None

    try:
        config.validate()
    except ValueError as e:
        print(f"\n  Configuration error: {e}")
        return None

    return config


# -- Summary ------------------------------------------------------------------

def _print_summary(config: ProjectConfig) -> None:
    print()
    print("  -- Summary --")
    print(f"  Project:    {config.project_name}")
    if config.backend:
        print(f"  Backend:    Python {config.backend.python_version} on port {config.backend.server_port}")
    if config.frontend and config.frontend.framework != FrontendFramework.NONE:
        fw = config.frontend.framework.value.capitalize()
        if config.frontend.framework != FrontendFramework.FLUTTER:
            fw += f" on port {config.frontend.server_port}"
        print(f"  Frontend:   {fw}")
        print(f"  Features:   {', '.join(config.frontend.features)}")
    else:
        print("  Frontend:   None")
    print(f"  Auth:       {'Keycloak' if config.include_keycloak else 'Disabled'}")
    if config.include_keycloak:
        print(f"  Keycloak:   port {config.keycloak_port}")
    print()


# -- Entry point --------------------------------------------------------------

def main() -> None:
    args = _parse_args()

    if _is_headless(args):
        # Headless mode: build config from file + flags
        cfg = _load_config_file(args.config) if args.config else {}
        try:
            config = _build_config(args, cfg)
            config.validate()
        except (ValueError, KeyError, json.JSONDecodeError) as e:
            print(f"  Configuration error: {e}")
            sys.exit(2)

        _print_summary(config)

        if not args.yes:
            if not _ask_confirm("Proceed with generation?"):
                print("\n  Aborted.")
                sys.exit(0)
    else:
        # Interactive mode
        config = _collect_inputs()
        if config is None:
            print("\n  Aborted.")
            sys.exit(0)

    print()
    project_root = generate(config)
    print(f"\n  Project generated at: {project_root}")

    if not args.no_docker and config.backend is not None:
        if args.yes:
            boot(project_root)
        else:
            print()
            if _ask_confirm("Start Docker Compose stack?", default=False):
                boot(project_root)
