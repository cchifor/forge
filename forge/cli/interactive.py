"""Interactive prompt flow for `forge` invoked without flags.

Uses questionary for the TUI. Tests patch ``forge.cli.questionary`` and
the ``_ask_*`` helpers via the re-exports on ``forge.cli``; both paths
(the re-export and the module-local name) resolve to the same callable.
"""

from __future__ import annotations

import sys

import questionary

from forge.cli.parser import COLOR_SCHEMES
from forge.config import (
    BACKEND_REGISTRY,
    DEFAULT_REALM,
    BackendConfig,
    FrontendConfig,
    FrontendFramework,
    ProjectConfig,
    keycloak_client_id_from,
    validate_features,
)


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


def _prompt_backend(
    index: int,
    project_name: str,
    description: str,
    default_port: int,
) -> BackendConfig:
    """Prompt the user for one backend's configuration.

    Drives language and version choices from BACKEND_REGISTRY so adding a 4th
    backend doesn't require touching this function.
    """
    default_name = "backend" if index == 0 else f"backend-{index}"
    name = _ask_text("Backend name:", default=default_name)
    label_to_lang = {spec.display_label: lang for lang, spec in BACKEND_REGISTRY.items()}
    chosen_label = _ask_select("Backend language:", choices=list(label_to_lang.keys()))
    language = label_to_lang[chosen_label]
    spec = BACKEND_REGISTRY[language]
    port = _ask_port("Backend server port:", default=str(default_port))
    version = _ask_select(f"{spec.display_label} version:", choices=list(spec.version_choices))
    features = _ask_features()

    return BackendConfig(
        name=name,
        project_name=project_name,
        language=language,
        description=description,
        features=features,
        server_port=port,
        **{spec.version_field: version},
    )


def _collect_inputs() -> ProjectConfig | None:
    # Fail fast if no terminal is available
    if not sys.stdin.isatty():
        print(
            "Error: Interactive mode requires a terminal.\n"
            "Use --config, --yes, or --json for headless mode.",
            file=sys.stderr,
        )
        sys.exit(2)

    print()
    print("  +===================================+")
    print("  |             forge                  |")
    print("  |      Project Generator             |")
    print("  +===================================+")
    print()

    project_name = _ask_text("Project name:", default="My Platform")
    description = _ask_text("Description:", default="A full-stack application")

    backends: list[BackendConfig] = []
    print()
    print("  -- Backend 1 --")
    backends.append(_prompt_backend(0, project_name, description, default_port=5000))

    while _ask_confirm("Add another backend?", default=False):
        print()
        print(f"  -- Backend {len(backends) + 1} --")
        backends.append(
            _prompt_backend(
                len(backends),
                project_name,
                description,
                default_port=5000 + len(backends),
            )
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
            include_openapi = _ask_confirm("Enable OpenAPI code generation?", default=False)

        color_scheme = "blue"
        if framework == FrontendFramework.VUE:
            color_scheme = _ask_select(
                "Default color scheme:",
                choices=COLOR_SCHEMES,
            )

        org_name = "com.example"
        if framework == FrontendFramework.FLUTTER:
            org_name = _ask_text("Organization name (reverse domain):", default="com.example")

        frontend = FrontendConfig(
            framework=framework,
            project_name=project_name,
            description=description,
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
        keycloak_port = _ask_port("Keycloak host port:", default="18080")
        kc_url = f"http://localhost:{keycloak_port}"
        kc_realm = _ask_text("Keycloak realm:", default=DEFAULT_REALM)
        kc_client_id = _ask_text(
            "Keycloak client ID:",
            default=keycloak_client_id_from(project_name),
        )

    if frontend and include_keycloak:
        frontend.keycloak_url = kc_url
        frontend.keycloak_realm = kc_realm
        frontend.keycloak_client_id = kc_client_id

    config = ProjectConfig(
        project_name=project_name,
        backends=backends,
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


def _print_summary(config: ProjectConfig) -> None:
    print()
    print("  -- Summary --")
    print(f"  Project:    {config.project_name}")
    if config.backend:
        print(
            f"  Backend:    Python {config.backend.python_version} on port {config.backend.server_port}"
        )
    if config.frontend and config.frontend.framework != FrontendFramework.NONE:
        fw = config.frontend.framework.value.capitalize()
        if config.frontend.framework != FrontendFramework.FLUTTER:
            fw += f" on port {config.frontend.server_port}"
        print(f"  Frontend:   {fw}")
        print(f"  Features:   {', '.join(config.all_features)}")
    else:
        print("  Frontend:   None")
    print(f"  Auth:       {'Keycloak' if config.include_keycloak else 'Disabled'}")
    if config.include_keycloak:
        print(f"  Keycloak:   port {config.keycloak_port}")
    print()
