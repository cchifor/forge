"""Interactive CLI entry point for forge-cli."""

from __future__ import annotations

import sys

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


# -- Prompt helpers -----------------------------------------------------------

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


# -- Main prompt flow ---------------------------------------------------------

def _collect_inputs() -> ProjectConfig | None:
    print()
    print("  +===================================+")
    print("  |             forge                  |")
    print("  |      Project Generator             |")
    print("  +===================================+")
    print()

    # -- Project basics --
    project_name = _ask_text("Project name:", default="My Platform")
    description = _ask_text("Description:", default="A full-stack application")

    # -- Backend --
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

    # -- Frontend --
    print()
    print("  -- Frontend --")
    fw_choice = _ask_select(
        "Frontend framework:",
        choices=["Vue 3", "Svelte 5", "Flutter", "None"],
    )
    framework_map = {
        "Vue 3": FrontendFramework.VUE,
        "Svelte 5": FrontendFramework.SVELTE,
        "Flutter": FrontendFramework.FLUTTER,
        "None": FrontendFramework.NONE,
    }
    framework = framework_map[fw_choice]

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
                "Default color scheme:",
                choices=[
                    "blue", "indigo", "teal", "green",
                    "deepPurple", "red", "amber", "cyan",
                ],
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

    # -- Keycloak --
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

    # Propagate keycloak settings to frontend
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

    # -- Confirmation --
    print()
    print("  -- Summary --")
    print(f"  Project:    {project_name}")
    print(f"  Backend:    Python {python_version} on port {backend_port}")
    if frontend:
        fw_label = fw_choice
        if framework != FrontendFramework.FLUTTER:
            fw_label += f" on port {frontend.server_port}"
        print(f"  Frontend:   {fw_label}")
        print(f"  Features:   {', '.join(frontend.features)}")
    else:
        print("  Frontend:   None")
    print(f"  Auth:       {'Keycloak' if include_auth else 'Disabled'}")
    if include_auth:
        print(f"  Keycloak:   port {keycloak_port}, realm '{kc_realm}'")
    print()

    if not _ask_confirm("Proceed with generation?"):
        return None

    try:
        config.validate()
    except ValueError as e:
        print(f"\n  Configuration error: {e}")
        return None

    return config


# -- Entry point --------------------------------------------------------------

def main() -> None:
    config = _collect_inputs()
    if config is None:
        print("\n  Aborted.")
        sys.exit(0)

    print()
    project_root = generate(config)
    print(f"\n  Project generated at: {project_root}")

    # Offer to boot Docker
    if config.backend is not None:
        print()
        if _ask_confirm("Start Docker Compose stack?", default=False):
            boot(project_root)
