"""CLI entry point for forge. Supports interactive and headless modes."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, cast

import questionary

from forge.config import (
    BACKEND_REGISTRY,
    BackendConfig,
    BackendLanguage,
    FrontendConfig,
    FrontendFramework,
    ProjectConfig,
    validate_features,
)
from forge.docker_manager import boot
from forge.generator import GeneratorError, generate

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
    p.add_argument(
        "--config", "-c", type=str, metavar="FILE", help="YAML/JSON config file (use - for stdin)"
    )

    # Project
    p.add_argument("--project-name", metavar="NAME")
    p.add_argument("--description", metavar="DESC")
    p.add_argument("--output-dir", metavar="DIR", default=".")

    # Backend
    p.add_argument(
        "--backend-language",
        choices=["python", "node", "rust"],
        help="Backend language: python (FastAPI), node (Fastify), or rust (Axum)",
    )
    p.add_argument("--backend-name", metavar="NAME", help="Backend service name (default: backend)")
    p.add_argument("--backend-port", type=int, metavar="PORT")
    p.add_argument("--python-version", choices=["3.13", "3.12", "3.11"])
    p.add_argument("--node-version", choices=["22", "24"])
    p.add_argument("--rust-edition", choices=["2021", "2024"])

    # Frontend
    p.add_argument("--frontend", choices=list(FRAMEWORK_MAP.keys()), metavar="FRAMEWORK")
    p.add_argument("--features", metavar="LIST", help="Comma-separated CRUD entities")
    p.add_argument("--author-name", metavar="NAME")
    p.add_argument("--package-manager", choices=["npm", "pnpm", "yarn", "bun"])
    p.add_argument("--frontend-port", type=int, metavar="PORT")
    p.add_argument("--color-scheme", choices=COLOR_SCHEMES)
    p.add_argument(
        "--org-name", metavar="ORG", help="Flutter org in reverse domain (e.g. com.example)"
    )

    # Feature toggles
    p.add_argument("--include-auth", action="store_true", default=None)
    p.add_argument("--no-auth", dest="include_auth", action="store_false")
    p.add_argument("--include-chat", action="store_true", default=None)
    p.add_argument("--include-openapi", action="store_true", default=None)
    p.add_argument(
        "--no-e2e-tests",
        dest="generate_e2e_tests",
        action="store_false",
        default=None,
        help="Skip Playwright e2e test generation",
    )

    # Keycloak
    p.add_argument("--keycloak-port", type=int, metavar="PORT")
    p.add_argument("--keycloak-realm", metavar="REALM")
    p.add_argument("--keycloak-client-id", metavar="ID")

    # Behavior
    p.add_argument("--yes", "-y", action="store_true", help="Skip confirmation prompts")
    p.add_argument("--no-docker", action="store_true", help="Skip Docker Compose boot")
    p.add_argument(
        "--quiet", "-q", action="store_true", help="Suppress progress output (implies quiet Copier)"
    )
    p.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show full Copier and subprocess output (overrides --quiet for diagnostics)",
    )
    p.add_argument(
        "--json",
        dest="json_output",
        action="store_true",
        help="Print machine-readable JSON result to stdout",
    )
    p.add_argument(
        "--completion",
        choices=["bash", "zsh", "fish"],
        metavar="SHELL",
        help="Print a shell completion script to stdout and exit",
    )

    return p.parse_args()


# -- Completion scripts -------------------------------------------------------

_BASH_COMPLETION = """\
_forge_completions() {
  local cur prev opts
  COMPREPLY=()
  cur="${COMP_WORDS[COMP_CWORD]}"
  prev="${COMP_WORDS[COMP_CWORD-1]}"
  opts="--config --project-name --description --output-dir --backend-language \\
        --backend-name --backend-port --python-version --node-version --rust-edition \\
        --frontend --features --author-name --package-manager --frontend-port \\
        --color-scheme --org-name --include-auth --no-auth --include-chat \\
        --include-openapi --no-e2e-tests --keycloak-port --keycloak-realm \\
        --keycloak-client-id --yes --no-docker --quiet --verbose --json --completion --help"
  case "$prev" in
    --backend-language) COMPREPLY=( $(compgen -W "python node rust" -- "$cur") ); return 0 ;;
    --frontend) COMPREPLY=( $(compgen -W "vue svelte flutter none" -- "$cur") ); return 0 ;;
    --package-manager) COMPREPLY=( $(compgen -W "npm pnpm yarn bun" -- "$cur") ); return 0 ;;
    --completion) COMPREPLY=( $(compgen -W "bash zsh fish" -- "$cur") ); return 0 ;;
    --config|--output-dir) COMPREPLY=( $(compgen -f -- "$cur") ); return 0 ;;
  esac
  COMPREPLY=( $(compgen -W "$opts" -- "$cur") )
}
complete -F _forge_completions forge
"""

_ZSH_COMPLETION = """\
#compdef forge
_forge() {
  local -a opts
  opts=(
    '--config[YAML/JSON config file]:file:_files'
    '--project-name[Project name]:name:'
    '--output-dir[Output directory]:dir:_files -/'
    '--backend-language[Backend language]:lang:(python node rust)'
    '--frontend[Frontend framework]:framework:(vue svelte flutter none)'
    '--package-manager[Package manager]:pm:(npm pnpm yarn bun)'
    '--yes[Skip confirmations]'
    '--no-docker[Skip Docker boot]'
    '--quiet[Suppress output]'
    '--verbose[Show full output]'
    '--json[Print JSON result]'
    '--completion[Print completion script]:shell:(bash zsh fish)'
  )
  _arguments $opts
}
_forge "$@"
"""

_FISH_COMPLETION = """\
complete -c forge -l config -d "YAML/JSON config file" -r
complete -c forge -l project-name -d "Project name" -x
complete -c forge -l output-dir -d "Output directory" -r
complete -c forge -l backend-language -d "Backend language" -xa "python node rust"
complete -c forge -l frontend -d "Frontend framework" -xa "vue svelte flutter none"
complete -c forge -l package-manager -d "Package manager" -xa "npm pnpm yarn bun"
complete -c forge -l yes -d "Skip confirmations"
complete -c forge -l no-docker -d "Skip Docker boot"
complete -c forge -l quiet -d "Suppress output"
complete -c forge -l verbose -d "Show full output"
complete -c forge -l json -d "Print JSON result"
complete -c forge -l completion -d "Print completion script" -xa "bash zsh fish"
"""

_COMPLETIONS = {"bash": _BASH_COMPLETION, "zsh": _ZSH_COMPLETION, "fish": _FISH_COMPLETION}


def _print_completion(shell: str) -> None:
    sys.stdout.write(_COMPLETIONS[shell])
    sys.exit(0)


def _is_headless(args: argparse.Namespace) -> bool:
    """Return True if any CLI flag or config file was provided."""
    return (
        args.config is not None
        or args.project_name is not None
        or args.frontend is not None
        or args.yes
        or args.quiet
        or getattr(args, "json_output", False)
        or args.no_docker
        or args.backend_port is not None
        or args.python_version is not None
        or args.features is not None
        or args.description is not None
    )


# -- Config file loading ------------------------------------------------------


def _load_config_file(path_str: str) -> dict[str, Any]:
    """Load YAML or JSON config. Use '-' for stdin."""
    try:
        import yaml

        has_yaml = True
    except ImportError:
        has_yaml = False

    try:
        if path_str == "-":
            raw = sys.stdin.read()
        else:
            p = Path(path_str)
            if not p.exists():
                raise FileNotFoundError(f"Config file not found: {p}")
            raw = p.read_text(encoding="utf-8")

        if not raw.strip():
            return {}

        is_yaml = path_str == "-" or Path(path_str).suffix in (".yml", ".yaml")
        if is_yaml and has_yaml:
            return yaml.safe_load(raw) or {}
        return json.loads(raw)
    except Exception as e:
        raise ValueError(f"Failed to load config: {e}") from e


# -- Build config from args/file ---------------------------------------------


def _get(
    args: argparse.Namespace,
    flag: str,
    cfg: dict[str, Any],
    *keys: str,
    default: Any = None,
) -> Any:
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


def _normalize_features(raw: Any, default: list[str] | None = None) -> list[str]:
    """Coerce CLI/config feature input (list or comma-string) to a clean list."""
    if raw is None:
        return list(default) if default else []
    if isinstance(raw, list):
        return [str(f).strip() for f in raw if str(f).strip()]
    return [f.strip() for f in str(raw).split(",") if f.strip()]


def _build_backends_from_cfg(
    args: argparse.Namespace, cfg: dict[str, Any], project_name: str, description: str
) -> list[BackendConfig]:
    """Build backend list from CLI args + config file.

    Supports both `backends:` (list) and `backend:` (single) for backward compatibility.
    """
    backends_raw = cfg.get("backends")
    if isinstance(backends_raw, list) and backends_raw:
        backends: list[BackendConfig] = []
        for i, raw in enumerate(backends_raw):
            if not isinstance(raw, dict):
                continue
            be_cfg = cast("dict[str, Any]", raw)
            lang = be_cfg.get("language", "python")
            language = (
                BackendLanguage(lang)
                if lang in ("python", "node", "rust")
                else BackendLanguage.PYTHON
            )
            backends.append(
                BackendConfig(
                    name=be_cfg.get("name", f"backend-{i}"),
                    project_name=project_name,
                    language=language,
                    description=be_cfg.get("description", description),
                    features=_normalize_features(be_cfg.get("features"), default=["items"]),
                    python_version=be_cfg.get("python_version", "3.13"),
                    node_version=be_cfg.get("node_version", "22"),
                    rust_edition=be_cfg.get("rust_edition", "2024"),
                    server_port=be_cfg.get("server_port", 5000 + i),
                )
            )
        return backends

    # Single backend (backward compat for `backend:` shape and CLI-only invocations)
    lang_str = _get(args, "backend_language", cfg, "backend", "language", default="python")
    language = (
        BackendLanguage(lang_str)
        if lang_str in ("python", "node", "rust")
        else BackendLanguage.PYTHON
    )
    return [
        BackendConfig(
            name=_get(args, "backend_name", cfg, "backend", "name", default="backend"),
            project_name=project_name,
            language=language,
            description=description,
            features=_normalize_features(
                _get(args, "features", cfg, "backend", "features", default=None),
                default=["items"],
            ),
            python_version=_get(
                args, "python_version", cfg, "backend", "python_version", default="3.13"
            ),
            node_version=_get(args, "node_version", cfg, "backend", "node_version", default="22"),
            rust_edition=_get(args, "rust_edition", cfg, "backend", "rust_edition", default="2024"),
            server_port=_get(args, "backend_port", cfg, "backend", "server_port", default=5000),
        )
    ]


def _build_frontend_from_cfg(
    args: argparse.Namespace, cfg: dict[str, Any], project_name: str, description: str
) -> tuple[FrontendConfig | None, bool]:
    """Build optional frontend config; returns (frontend, include_auth)."""
    fw_str = _get(args, "frontend", cfg, "frontend", "framework", default="none")
    framework = FRAMEWORK_MAP.get(fw_str, FrontendFramework.NONE)
    if framework == FrontendFramework.NONE:
        return None, False

    include_auth = _get(args, "include_auth", cfg, "frontend", "include_auth", default=True)
    frontend = FrontendConfig(
        framework=framework,
        project_name=project_name,
        description=description,
        author_name=_get(args, "author_name", cfg, "frontend", "author_name", default="Your Name"),
        package_manager=_get(
            args, "package_manager", cfg, "frontend", "package_manager", default="npm"
        ),
        include_auth=include_auth,
        include_chat=_get(args, "include_chat", cfg, "frontend", "include_chat", default=False),
        include_openapi=_get(
            args, "include_openapi", cfg, "frontend", "include_openapi", default=False
        ),
        server_port=_get(args, "frontend_port", cfg, "frontend", "server_port", default=5173),
        default_color_scheme=_get(
            args, "color_scheme", cfg, "frontend", "default_color_scheme", default="blue"
        ),
        org_name=_get(args, "org_name", cfg, "frontend", "org_name", default="com.example"),
        generate_e2e_tests=_get(
            args, "generate_e2e_tests", cfg, "frontend", "generate_e2e_tests", default=True
        ),
    )
    return frontend, include_auth


def _build_config(args: argparse.Namespace, cfg: dict[str, Any]) -> ProjectConfig:
    """Build ProjectConfig from CLI args merged with config file."""
    project_name = _get(args, "project_name", cfg, "project_name", default="My Platform")
    description = _get(args, "description", cfg, "description", default="A full-stack application")
    output_dir = args.output_dir

    backends = _build_backends_from_cfg(args, cfg, project_name, description)
    frontend, include_auth = _build_frontend_from_cfg(args, cfg, project_name, description)

    # Keycloak
    include_keycloak = include_auth
    keycloak_port = _get(args, "keycloak_port", cfg, "keycloak", "port", default=18080)
    kc_realm = _get(
        args,
        "keycloak_realm",
        cfg,
        "keycloak",
        "realm",
        default="app",  # matches Host(`app.localhost`) for Gatekeeper tenant extraction
    )
    kc_client_id = _get(
        args,
        "keycloak_client_id",
        cfg,
        "keycloak",
        "client_id",
        default=project_name.lower().replace(" ", "-").replace("_", "-"),
    )

    if frontend and include_keycloak:
        frontend.keycloak_url = f"http://localhost:{keycloak_port}"
        frontend.keycloak_realm = kc_realm
        frontend.keycloak_client_id = kc_client_id

    return ProjectConfig(
        project_name=project_name,
        output_dir=str(output_dir),
        backends=backends,
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

    bc = BackendConfig(
        name=name,
        project_name=project_name,
        language=language,
        description=description,
        features=features,
        server_port=port,
    )
    setattr(bc, spec.version_field, version)
    return bc


# -- Interactive flow ---------------------------------------------------------


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
        kc_realm = _ask_text(
            "Keycloak realm:",
            default="app",  # matches Host(`app.localhost`) for Gatekeeper tenant extraction
        )
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


# -- Summary ------------------------------------------------------------------


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


# -- Entry point --------------------------------------------------------------


def _json_error(stdout_fd, message: str) -> None:
    """Write a JSON error object to the real stdout and exit."""
    stdout_fd.write(json.dumps({"error": message}) + "\n")
    stdout_fd.flush()
    sys.exit(2)


def main() -> None:
    args = _parse_args()

    if getattr(args, "completion", None):
        _print_completion(args.completion)

    # When --json is set, redirect all print() to stderr so stdout is clean JSON
    _real_stdout = sys.stdout
    if getattr(args, "json_output", False):
        sys.stdout = sys.stderr

    if _is_headless(args):
        # Headless mode: build config from file + flags
        try:
            cfg = _load_config_file(args.config) if args.config else {}
        except ValueError as e:
            if getattr(args, "json_output", False):
                _json_error(_real_stdout, str(e))
            print(f"  Configuration error: {e}", file=sys.stderr)
            sys.exit(2)

        try:
            config = _build_config(args, cfg)
            config.validate()
        except (ValueError, KeyError) as e:
            if getattr(args, "json_output", False):
                _json_error(_real_stdout, str(e))
            print(f"  Configuration error: {e}", file=sys.stderr)
            sys.exit(2)

        if not args.quiet and not getattr(args, "json_output", False):
            _print_summary(config)

        if not args.yes and not _ask_confirm("Proceed with generation?"):
            print("\n  Aborted.")
            sys.exit(0)
    else:
        # Interactive mode
        config = _collect_inputs()
        if config is None:
            print("\n  Aborted.")
            sys.exit(0)

    # --verbose overrides --quiet so users can diagnose generator failures even in JSON mode.
    quiet = (args.quiet or getattr(args, "json_output", False)) and not getattr(
        args, "verbose", False
    )

    if not quiet:
        print()
    try:
        project_root = generate(config, quiet=quiet)
    except GeneratorError as e:
        if getattr(args, "json_output", False):
            _json_error(_real_stdout, str(e))
        print(f"\n  Generation failed: {e}", file=sys.stderr)
        sys.exit(2)

    if getattr(args, "json_output", False):
        result: dict[str, Any] = {"project_root": str(project_root)}
        if config.backends:
            result["backends"] = [
                {
                    "name": bc.name,
                    "dir": str(project_root / bc.name),
                    "language": bc.language.value,
                    "port": bc.server_port,
                }
                for bc in config.backends
            ]
            # Backward compat: single backend_dir for first backend
            result["backend_dir"] = str(project_root / config.backends[0].name)
        if config.frontend and config.frontend.framework != FrontendFramework.NONE:
            result["frontend_dir"] = str(project_root / config.frontend_slug)
            result["framework"] = config.frontend.framework.value
            result["features"] = config.all_features
        _real_stdout.write(json.dumps(result) + "\n")
        _real_stdout.flush()
    else:
        if not quiet:
            print(f"\n  Project generated at: {project_root}")

    if not args.no_docker and config.backend is not None:
        if args.yes:
            boot(project_root)
        else:
            print()
            if _ask_confirm("Start Docker Compose stack?", default=False):
                boot(project_root)
