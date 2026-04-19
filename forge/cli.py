"""CLI entry point for forge. Supports interactive and headless modes."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import textwrap
from pathlib import Path
from typing import Any, cast

import questionary

from forge.config import (
    BACKEND_REGISTRY,
    DEFAULT_REALM,
    BackendConfig,
    BackendLanguage,
    FrontendConfig,
    FrontendFramework,
    ProjectConfig,
    keycloak_client_id_from,
    validate_features,
)
from forge.docker_manager import boot
from forge.errors import GeneratorError
from forge.generator import generate
from forge.options import (
    CATEGORY_DISPLAY,
    OPTION_REGISTRY,
    Option,
    OptionType,
    ordered_options,
    to_json_schema,
)

# -- Argument parsing ---------------------------------------------------------

FRAMEWORK_MAP = {
    "vue": FrontendFramework.VUE,
    "svelte": FrontendFramework.SVELTE,
    "flutter": FrontendFramework.FLUTTER,
    "none": FrontendFramework.NONE,
}

COLOR_SCHEMES = ["blue", "indigo", "teal", "green", "deepPurple", "red", "amber", "cyan"]


def _build_parser() -> argparse.ArgumentParser:
    """Construct the argparse parser without consuming ``sys.argv``.

    Split from ``_parse_args`` so the completion-script builders (and
    the parity test) can introspect registered flags without actually
    parsing anything.
    """
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

    # Frontend toggles
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

    # Options — the unified config surface.
    p.add_argument(
        "--set",
        dest="set_options",
        action="append",
        metavar="PATH=VALUE",
        default=[],
        help="Set an option (repeatable). Example: --set rag.backend=qdrant.",
    )
    p.add_argument(
        "--list",
        action="store_true",
        help=(
            "Print the option registry and exit. Pair with --format "
            "{text,json,yaml} to pick the output shape."
        ),
    )
    p.add_argument(
        "--describe",
        metavar="PATH",
        help="Print the full description for one option path and exit.",
    )
    p.add_argument(
        "--schema",
        action="store_true",
        help="Print the JSON Schema 2020-12 document for the option registry and exit.",
    )
    p.add_argument(
        "--format",
        dest="format",
        choices=["text", "json", "yaml"],
        default=None,
        help="Output format for --list. Defaults to text.",
    )

    # Update
    p.add_argument(
        "--update",
        action="store_true",
        help=(
            "Update an existing forge-generated project in-place: re-apply "
            "option fragments (idempotent) and re-stamp forge.toml. Run "
            "from the project root or pass --project-path."
        ),
    )
    p.add_argument(
        "--project-path",
        metavar="DIR",
        default=".",
        help="Target directory for --update. Defaults to the current directory.",
    )

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

    return p


def _parse_args() -> argparse.Namespace:
    return _build_parser().parse_args()


# -- Completion scripts -------------------------------------------------------
#
# Generated once at module load by introspecting the parser returned by
# ``_build_parser()``. Every flag registered in argparse is guaranteed to
# appear in every shell's script, so adding / renaming / removing a flag
# updates completions automatically. Tests in
# ``tests/test_cli_completion.py`` assert this parity.


def _flag_actions(parser: argparse.ArgumentParser) -> list[argparse.Action]:
    """Every option-bearing action on the parser, in registration order.

    Includes argparse's auto-added ``-h / --help``.
    """
    return [a for a in parser._actions if a.option_strings]


def _action_help_short(action: argparse.Action) -> str:
    """Short (first-sentence) help text for a completion tooltip."""
    text = action.help or action.dest.replace("_", " ")
    # First sentence only; cap length so zsh brackets stay readable.
    first = text.split(". ", 1)[0].rstrip(".")
    return first[:70]


def _metavar_str(action: argparse.Action) -> str:
    """Return the action's metavar as a plain string (or '' if unset/tuple)."""
    mv = action.metavar
    if isinstance(mv, str):
        return mv
    return ""


def _action_path_kind(action: argparse.Action) -> str | None:
    """Return 'file' or 'dir' when an action wants a path, else ``None``."""
    mv = _metavar_str(action).upper()
    if mv == "FILE":
        return "file"
    if mv == "DIR":
        return "dir"
    return None


def _bash_completion_script(parser: argparse.ArgumentParser) -> str:
    """Emit a bash completion script covering every flag on the parser."""
    actions = _flag_actions(parser)
    long_flags = [o for a in actions for o in a.option_strings if o.startswith("--")]
    short_flags = [
        o for a in actions for o in a.option_strings if len(o) == 2 and o.startswith("-")
    ]
    opts_line = " ".join(long_flags + short_flags)

    cases: list[str] = []
    for action in actions:
        long_opts = [o for o in action.option_strings if o.startswith("--")]
        if not long_opts:
            continue
        pattern = "|".join(long_opts)
        if action.choices:
            choices = " ".join(str(c) for c in action.choices)
            cases.append(
                f'    {pattern}) COMPREPLY=( $(compgen -W "{choices}" -- "$cur") ); return 0 ;;'
            )
    path_flags = [
        o
        for a in actions
        for o in a.option_strings
        if o.startswith("--") and _action_path_kind(a) is not None
    ]
    if path_flags:
        pattern = "|".join(path_flags)
        cases.append(f'    {pattern}) COMPREPLY=( $(compgen -f -- "$cur") ); return 0 ;;')

    cases_block = "\n".join(cases) or "    *) ;;"
    return (
        "_forge_completions() {\n"
        "  local cur prev opts\n"
        "  COMPREPLY=()\n"
        '  cur="${COMP_WORDS[COMP_CWORD]}"\n'
        '  prev="${COMP_WORDS[COMP_CWORD-1]}"\n'
        f'  opts="{opts_line}"\n'
        '  case "$prev" in\n'
        f"{cases_block}\n"
        "  esac\n"
        '  COMPREPLY=( $(compgen -W "$opts" -- "$cur") )\n'
        "}\n"
        "complete -F _forge_completions forge\n"
    )


def _zsh_completion_script(parser: argparse.ArgumentParser) -> str:
    """Emit a zsh ``_arguments``-style completion script."""
    lines = ["#compdef forge", "_forge() {", "  local -a opts", "  opts=("]
    for action in _flag_actions(parser):
        help_text = (
            _action_help_short(action).replace("'", "'\\''").replace("[", "(").replace("]", ")")
        )
        path_kind = _action_path_kind(action)
        for flag in action.option_strings:
            # Zsh _arguments accepts both --long and -s (short) as separate entries.
            metavar = _metavar_str(action)
            if action.choices:
                choices = " ".join(str(c) for c in action.choices)
                mv = (metavar or action.dest).lower()
                lines.append(f"    '{flag}[{help_text}]:{mv}:({choices})'")
            elif path_kind == "file":
                lines.append(f"    '{flag}[{help_text}]:file:_files'")
            elif path_kind == "dir":
                lines.append(f"    '{flag}[{help_text}]:dir:_files -/'")
            elif metavar:
                lines.append(f"    '{flag}[{help_text}]:{metavar.lower()}:'")
            else:
                lines.append(f"    '{flag}[{help_text}]'")
    lines.extend(["  )", "  _arguments $opts", "}", '_forge "$@"'])
    return "\n".join(lines) + "\n"


def _fish_completion_script(parser: argparse.ArgumentParser) -> str:
    """Emit a fish completion script, one ``complete`` directive per action."""
    lines: list[str] = []
    for action in _flag_actions(parser):
        longs = [o[2:] for o in action.option_strings if o.startswith("--")]
        shorts = [o[1:] for o in action.option_strings if len(o) == 2 and o.startswith("-")]
        if not longs:
            continue
        long = longs[0]
        help_text = _action_help_short(action).replace('"', '\\"')
        parts = ["complete", "-c", "forge", "-l", long]
        if shorts:
            parts.extend(["-s", shorts[0]])
        parts.extend(["-d", f'"{help_text}"'])
        if action.choices:
            choices = " ".join(str(c) for c in action.choices)
            parts.extend(["-xa", f'"{choices}"'])
        elif _action_path_kind(action) is not None:
            parts.append("-r")
        lines.append(" ".join(parts))
        # Also emit a line for any extra long flags (e.g. --no-auth sharing dest with --include-auth)
        for extra_long in longs[1:]:
            extra = ["complete", "-c", "forge", "-l", extra_long, "-d", f'"{help_text}"']
            lines.append(" ".join(extra))
    return "\n".join(lines) + "\n"


_PARSER_FOR_COMPLETION = _build_parser()
_BASH_COMPLETION = _bash_completion_script(_PARSER_FOR_COMPLETION)
_ZSH_COMPLETION = _zsh_completion_script(_PARSER_FOR_COMPLETION)
_FISH_COMPLETION = _fish_completion_script(_PARSER_FOR_COMPLETION)
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
        or bool(getattr(args, "set_options", []))
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


class _Resolver:
    """Bundles `args` + parsed config file for the duration of _build_config.

    Replaces threading `(args, cfg, ...)` through every helper and drops the
    first two positional arguments from each lookup. Call-sites go from
    `_get(args, "frontend_port", cfg, "frontend", "server_port", default=5173)`
    to `r.get("frontend_port", "frontend", "server_port", default=5173)`.
    """

    def __init__(self, args: argparse.Namespace, cfg: dict[str, Any]) -> None:
        self.args = args
        self.cfg = cfg

    def get(self, flag: str, *keys: str, default: Any = None) -> Any:
        """Resolve a value: CLI flag > config file > default."""
        val = getattr(self.args, flag, None)
        if val is not None:
            return val
        node: Any = self.cfg
        for k in keys:
            if isinstance(node, dict):
                node = node.get(k)
            else:
                return default
        return node if node is not None else default


def _normalize_features(raw: Any, default: list[str] | None = None) -> list[str]:
    """Coerce CLI/config feature input (list or comma-string) to a clean list."""
    if raw is None:
        return list(default) if default else []
    if isinstance(raw, list):
        return [str(f).strip() for f in raw if str(f).strip()]
    return [f.strip() for f in str(raw).split(",") if f.strip()]


def _build_backends_from_cfg(
    r: _Resolver, project_name: str, description: str
) -> list[BackendConfig]:
    """Build backend list from CLI args + config file.

    Supports both `backends:` (list) and `backend:` (single) for backward compatibility.
    """
    backends_raw = r.cfg.get("backends")
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
    lang_str = r.get("backend_language", "backend", "language", default="python")
    language = (
        BackendLanguage(lang_str)
        if lang_str in ("python", "node", "rust")
        else BackendLanguage.PYTHON
    )
    return [
        BackendConfig(
            name=r.get("backend_name", "backend", "name", default="backend"),
            project_name=project_name,
            language=language,
            description=description,
            features=_normalize_features(
                r.get("features", "backend", "features", default=None),
                default=["items"],
            ),
            python_version=r.get("python_version", "backend", "python_version", default="3.13"),
            node_version=r.get("node_version", "backend", "node_version", default="22"),
            rust_edition=r.get("rust_edition", "backend", "rust_edition", default="2024"),
            server_port=r.get("backend_port", "backend", "server_port", default=5000),
        )
    ]


def _build_frontend_from_cfg(
    r: _Resolver, project_name: str, description: str
) -> tuple[FrontendConfig | None, bool]:
    """Build optional frontend config; returns (frontend, include_auth)."""
    fw_str = r.get("frontend", "frontend", "framework", default="none")
    framework = FRAMEWORK_MAP.get(fw_str, FrontendFramework.NONE)
    if framework == FrontendFramework.NONE:
        return None, False

    include_auth = r.get("include_auth", "frontend", "include_auth", default=True)
    frontend = FrontendConfig(
        framework=framework,
        project_name=project_name,
        description=description,
        author_name=r.get("author_name", "frontend", "author_name", default="Your Name"),
        package_manager=r.get("package_manager", "frontend", "package_manager", default="npm"),
        include_auth=include_auth,
        include_chat=r.get("include_chat", "frontend", "include_chat", default=False),
        include_openapi=r.get("include_openapi", "frontend", "include_openapi", default=False),
        server_port=r.get("frontend_port", "frontend", "server_port", default=5173),
        default_color_scheme=r.get(
            "color_scheme", "frontend", "default_color_scheme", default="blue"
        ),
        org_name=r.get("org_name", "frontend", "org_name", default="com.example"),
        generate_e2e_tests=r.get(
            "generate_e2e_tests", "frontend", "generate_e2e_tests", default=True
        ),
    )
    return frontend, include_auth


# -- Options parsing ---------------------------------------------------------


def _flatten_nested(raw: Any, prefix: str = "") -> dict[str, Any]:
    """Turn nested dict form into dotted-key form.

    YAML users can write
        options:
          middleware:
            rate_limit: false
    which parses to ``{"middleware": {"rate_limit": False}}``. This
    function flattens it into ``{"middleware.rate_limit": False}`` so the
    rest of the pipeline only ever sees dotted keys. Values that are
    already scalars / lists pass through unchanged.
    """
    out: dict[str, Any] = {}
    if not isinstance(raw, dict):
        return out
    for key, value in raw.items():
        path = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(value, dict):
            out.update(_flatten_nested(value, prefix=path))
        else:
            out[path] = value
    return out


def _coerce_set_value(path: str, raw: str) -> Any:
    """Convert a ``--set PATH=VALUE`` string to the Option's native type.

    Unknown paths pass through as strings; ``ProjectConfig._validate_options``
    surfaces the typo. For known paths, bool / int / enum values are
    coerced here so ``--set rag.top_k=5`` reaches the resolver as ``5``
    (int), not ``"5"``. Enums with non-string underlying types (rare)
    best-effort-coerce to int.
    """
    opt = OPTION_REGISTRY.get(path)
    if opt is None:
        return raw
    if opt.type is OptionType.BOOL:
        lower = raw.strip().lower()
        if lower in ("true", "1", "yes", "on"):
            return True
        if lower in ("false", "0", "no", "off"):
            return False
        raise ValueError(f"--set {path}=<value>: expected true/false, got {raw!r}")
    if opt.type is OptionType.INT:
        try:
            return int(raw)
        except ValueError as e:
            raise ValueError(f"--set {path}=<value>: expected integer, got {raw!r}") from e
    if opt.type is OptionType.ENUM and opt.options:
        sample = opt.options[0]
        if isinstance(sample, bool):
            # No registered bool-valued enums today; keep the branch for safety.
            lower = raw.strip().lower()
            if lower in ("true", "false"):
                return lower == "true"
        if isinstance(sample, int) and not isinstance(sample, bool):
            try:
                return int(raw)
            except ValueError:
                return raw  # let the validator surface the error
    if opt.type is OptionType.LIST:
        return [v.strip() for v in raw.split(",") if v.strip()]
    return raw


def _build_options(args: argparse.Namespace, cfg: dict[str, Any]) -> dict[str, Any]:
    """Merge YAML ``options:`` block with ``--set`` repeats.

    YAML accepts both dotted and nested forms:

        options:
          middleware.rate_limit: false
          rag.backend: qdrant

        options:
          middleware:
            rate_limit: false
          rag:
            backend: qdrant

    ``--set`` always wins over YAML. Unknown paths and out-of-range
    values are rejected in ``ProjectConfig._validate_options`` so every
    entry point funnels through the same error path.
    """
    options: dict[str, Any] = {}

    yaml_block = cfg.get("options")
    if isinstance(yaml_block, dict):
        options.update(_flatten_nested(yaml_block))

    for entry in getattr(args, "set_options", None) or []:
        if "=" not in entry:
            raise ValueError(f"--set expects PATH=VALUE, got {entry!r}")
        path, raw_value = entry.split("=", 1)
        options[path.strip()] = _coerce_set_value(path.strip(), raw_value.strip())

    return options


def _build_config(args: argparse.Namespace, cfg: dict[str, Any]) -> ProjectConfig:
    """Build ProjectConfig from CLI args merged with config file."""
    r = _Resolver(args, cfg)
    project_name = r.get("project_name", "project_name", default="My Platform")
    description = r.get("description", "description", default="A full-stack application")
    output_dir = args.output_dir

    backends = _build_backends_from_cfg(r, project_name, description)
    frontend, include_auth = _build_frontend_from_cfg(r, project_name, description)
    options = _build_options(args, cfg)

    # Keycloak
    include_keycloak = include_auth
    keycloak_port = r.get("keycloak_port", "keycloak", "port", default=18080)
    kc_realm = r.get("keycloak_realm", "keycloak", "realm", default=DEFAULT_REALM)
    kc_client_id = r.get(
        "keycloak_client_id",
        "keycloak",
        "client_id",
        default=keycloak_client_id_from(project_name),
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
        options=options,
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

    return BackendConfig(
        name=name,
        project_name=project_name,
        language=language,
        description=description,
        features=features,
        server_port=port,
        **{spec.version_field: version},
    )


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


# -- Option catalogue rendering ----------------------------------------------
#
# Unified rows for the whole OPTION_REGISTRY feed three formatters:
#   - `_format_text` — two-column table with TTY-adaptive wrap.
#   - `_format_json` — bare flat JSON array for agent pipelines.
#   - `_format_yaml` — flat YAML list.
# Every row has the same keys so callers that filter / sort / render do
# not care which OptionType produced it. Diagnostics go to stderr; stdout
# is purely the serialized payload.


def _option_backends(_opt: Option) -> list[str]:
    """Backend languages this option's fragments target.

    Walks every fragment key in ``opt.enables`` and aggregates the
    implementations' backend languages. For simple Options this is
    usually ``["python"]``; middleware and observability Options span
    all three backends.
    """
    from forge.fragments import FRAGMENT_REGISTRY  # noqa: PLC0415

    langs: set[str] = set()
    for frag_keys in _opt.enables.values():
        for fkey in frag_keys:
            frag = FRAGMENT_REGISTRY.get(fkey)
            if frag is None:
                continue
            langs.update(lang.value for lang in frag.implementations)
    return sorted(langs)


def _build_option_rows() -> list[dict[str, Any]]:
    """Unified option catalogue.

    One row per registered Option, ordered by (category, path). Rows
    include enough metadata for both the text table and the JSON / YAML
    payloads; callers pick the subset that makes sense for their format.
    """
    rows: list[dict[str, Any]] = []
    for opt in ordered_options():
        if opt.hidden:
            continue
        rows.append(
            {
                "name": opt.path,
                "type": opt.type.value,
                "category": opt.category.value,
                "default": opt.default,
                "options": list(opt.options),
                "tech": _option_backends(opt),
                "description": opt.summary,
                "stability": opt.stability,
                "min": opt.min,
                "max": opt.max,
                "pattern": opt.pattern,
            }
        )
    return rows


_DEFAULT_TEXT_COLUMNS: tuple[tuple[str, str], ...] = (
    ("NAME", "name"),
    ("DESCRIPTION", "description"),
)
_TEXT_COLUMN_PAD = 3


def _description_cell(row: dict[str, Any]) -> str:
    """DESCRIPTION column text.

    Enum rows get their option list appended in ``[a, b, c]`` form so
    the allowed values are visible without needing ``--format json``.
    Bool rows render their summary unchanged.
    """
    summary = row.get("description") or ""
    if row.get("type") == OptionType.ENUM.value:
        options = row.get("options") or []
        if options and len(options) > 1:  # skip degenerate always-on enums
            return f"{summary} [{', '.join(str(v) for v in options)}]"
    return str(summary)


def _wrap_cols() -> int | None:
    """Return terminal width for wrapping the DESCRIPTION column, or None.

    Returns ``None`` when wrapping must be disabled:
      * stdout isn't a TTY (piped / redirected / pytest capsys) —
        downstream tools and tests expect byte-stable rows.
      * ``shutil.get_terminal_size`` fails or reports 0 cols (no
        controlling terminal, or a headless CI runner).
    """
    try:
        if not sys.stdout.isatty():
            return None
    except (ValueError, OSError):
        return None
    try:
        cols, _rows = shutil.get_terminal_size(fallback=(0, 0))
    except OSError:
        return None
    return cols if cols > 0 else None


def _format_text(
    rows: list[dict[str, Any]],
    columns: tuple[tuple[str, str], ...] = _DEFAULT_TEXT_COLUMNS,
) -> str:
    """Columnar table with a header row; last column runs to end of line.

    Column widths are computed from the actual rows so narrow catalogues
    align tightly and wider ones expand. List fields (when exposed as a
    column) render as ``[a, b, c]``.
    """

    def cell(row: dict[str, Any], field: str) -> str:
        if field == "description":
            return _description_cell(row)
        value = row.get(field)
        if isinstance(value, list):
            return "[" + ", ".join(str(v) for v in value) + "]"
        return "" if value is None else str(value)

    widths: dict[str, int] = {}
    for header, field in columns[:-1]:
        widest = max((len(cell(r, field)) for r in rows), default=0)
        widths[field] = max(widest, len(header)) + _TEXT_COLUMN_PAD

    lines: list[str] = []
    header_parts: list[str] = []
    for header, field in columns[:-1]:
        header_parts.append(header.ljust(widths[field]))
    header_parts.append(columns[-1][0])
    lines.append("".join(header_parts))

    prefix_len = sum(widths[f] for _, f in columns[:-1])
    wrap_cols = _wrap_cols()
    last_field = columns[-1][1]
    tail_width: int | None = None
    if wrap_cols is not None:
        candidate = max(wrap_cols - prefix_len, 20)
        longest = max((len(cell(r, last_field)) for r in rows), default=0)
        if longest > candidate:
            tail_width = candidate

    continuation_indent = " " * prefix_len

    for row in rows:
        parts: list[str] = []
        for _header, field in columns[:-1]:
            parts.append(cell(row, field).ljust(widths[field]))
        head = "".join(parts)
        tail = cell(row, last_field)

        if tail_width is None or len(tail) <= tail_width:
            lines.append(head + tail)
            continue

        chunks = textwrap.wrap(
            tail,
            width=tail_width,
            break_long_words=False,
            break_on_hyphens=False,
        )
        if not chunks:
            lines.append(head + tail)
            continue
        lines.append(head + chunks[0])
        for cont in chunks[1:]:
            lines.append(continuation_indent + cont)

    return "\n".join(lines) + "\n"


def _format_json(rows: list[dict[str, Any]]) -> str:
    """Bare flat JSON array. Every field from the catalogue is emitted —
    agents filter to what they need."""
    return json.dumps(rows, indent=2, default=str) + "\n"


def _format_yaml(rows: list[dict[str, Any]]) -> str:
    """Flat YAML list using the same field order the builder set."""
    import yaml

    return yaml.safe_dump(rows, sort_keys=False, default_flow_style=False, allow_unicode=True)


def _dispatch_list(fmt: str) -> None:
    """Build the option catalogue once; format; print to stdout; exit."""
    rows = _build_option_rows()
    if not rows:
        print("No options registered.", file=sys.stderr)

    try:
        if fmt == "json":
            payload = _format_json(rows)
        elif fmt == "yaml":
            payload = _format_yaml(rows)
        else:
            payload = _format_text(rows, columns=_DEFAULT_TEXT_COLUMNS)
    except Exception as exc:  # noqa: BLE001
        print(f"error: failed to render catalogue: {exc}", file=sys.stderr)
        sys.exit(1)

    sys.stdout.write(payload)
    sys.exit(0)


def _dispatch_schema() -> None:
    """Print the JSON Schema 2020-12 document for the registry and exit."""
    sys.stdout.write(json.dumps(to_json_schema(), indent=2) + "\n")
    sys.exit(0)


def _describe_option(path: str) -> None:
    """Print the full description block for one Option path and exit.

    Close-match suggestion covers typos ("rag_backend" -> "rag.backend").
    """
    opt = OPTION_REGISTRY.get(path)
    if opt is None:
        import difflib

        matches = difflib.get_close_matches(path, list(OPTION_REGISTRY), n=3, cutoff=0.5)
        suggestion = f" Did you mean: {', '.join(matches)}?" if matches else ""
        print(f"Unknown option {path!r}.{suggestion}", file=sys.stderr)
        sys.exit(1)

    backends = ", ".join(_option_backends(opt)) or "—"
    category = CATEGORY_DISPLAY[opt.category]

    print(f"{opt.path}  [{opt.type.value}]")
    print(f"Category: {category}")
    parts = [f"Default: {opt.default}", f"Stability: {opt.stability}", f"Backends: {backends}"]
    print("    ".join(parts))
    if opt.options:
        print(f"Allowed:  {', '.join(str(v) for v in opt.options)}")
    if opt.min is not None or opt.max is not None:
        bounds = []
        if opt.min is not None:
            bounds.append(f"min={opt.min}")
        if opt.max is not None:
            bounds.append(f"max={opt.max}")
        print(f"Bounds:   {', '.join(bounds)}")
    if opt.pattern is not None:
        print(f"Pattern:  {opt.pattern}")
    if opt.enables:
        print()
        print("Per-value fragment enables:")
        if opt.type is OptionType.BOOL:
            for val in (True, False):
                fragments = opt.enables.get(val, ())
                if fragments:
                    print(f"  {str(val):<12} -> {', '.join(fragments)}")
        else:
            for val in opt.options:
                fragments = opt.enables.get(val, ())
                if fragments:
                    print(f"  {str(val):<12} -> {', '.join(fragments)}")
                else:
                    print(f"  {str(val):<12} -> (no fragments)")
    print()
    print(opt.description or "(no description)")
    sys.exit(0)


def _run_update(args: argparse.Namespace) -> None:
    """Run `forge update` against the given project and exit."""
    from forge.errors import GeneratorError as _GeneratorError
    from forge.updater import update_project

    project_path = Path(getattr(args, "project_path", ".")).resolve()
    quiet = bool(getattr(args, "quiet", False))

    if not quiet:
        print(f"forge update: {project_path}")
    try:
        summary = update_project(project_path, quiet=quiet)
    except _GeneratorError as exc:
        if getattr(args, "json_output", False):
            print(json.dumps({"error": str(exc)}))
        else:
            print(f"error: {exc}", file=sys.stderr)
        sys.exit(2)

    if getattr(args, "json_output", False):
        print(json.dumps(summary, indent=2))
    elif not quiet:
        before = summary["forge_version_before"]
        after = summary["forge_version_after"]
        backends = cast("list[str]", summary["backends"])
        fragments_applied = cast("list[str]", summary["fragments_applied"])
        frags = ", ".join(fragments_applied) or "(none)"
        print(f"  forge {before} -> {after}")
        print(f"  backends: {', '.join(backends)}")
        print(f"  fragments: {frags}")
        print("Update complete.")
    sys.exit(0)


def main() -> None:
    args = _parse_args()

    if getattr(args, "list", False):
        fmt = getattr(args, "format", None) or "text"
        _dispatch_list(fmt)

    if getattr(args, "schema", False):
        _dispatch_schema()

    if getattr(args, "describe", None):
        _describe_option(args.describe)

    if getattr(args, "update", False):
        _run_update(args)

    if getattr(args, "completion", None):
        _print_completion(args.completion)

    # When --json is set, redirect all print() to stderr so stdout is clean JSON
    _real_stdout = sys.stdout
    if getattr(args, "json_output", False):
        sys.stdout = sys.stderr

    config: ProjectConfig
    if _is_headless(args):
        # Headless mode: build config from file + flags
        try:
            cfg = _load_config_file(args.config) if args.config else {}
        except ValueError as e:
            if getattr(args, "json_output", False):
                _json_error(_real_stdout, str(e))
            print(f"  Configuration error: {e}", file=sys.stderr)
            sys.exit(2)

        # Reject legacy YAML sections (features:, parameters:) up front so
        # users get a clean "regenerate your stack.yaml" message instead
        # of a silent pass through.
        for legacy in ("features", "parameters"):
            if legacy in cfg:
                msg = (
                    f"Legacy `{legacy}:` block in config. The current forge uses "
                    "`options:` with dotted paths (e.g. rag.backend). "
                    "See `forge --list` for the new shape."
                )
                if getattr(args, "json_output", False):
                    _json_error(_real_stdout, msg)
                print(f"  Configuration error: {msg}", file=sys.stderr)
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
        collected = _collect_inputs()
        if collected is None:
            print("\n  Aborted.")
            sys.exit(0)
        config = collected

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
