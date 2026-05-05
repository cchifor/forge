"""Argparse parser construction, shell-framework maps, and argument parsing.

Split from the old monolithic ``forge/cli.py``. The parser is built in
``_build_parser()`` — shared between ``_parse_args()`` (the runtime) and
the completion generators (which introspect without consuming argv).
"""

from __future__ import annotations

import argparse

from forge.config import FrontendFramework

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
    p.add_argument(
        "--mode",
        dest="update_mode",
        choices=["merge", "skip", "overwrite"],
        default="merge",
        help=(
            "Collision policy for --update when a fragment file already exists "
            "on disk. 'merge' (default) three-way-decides against the "
            "manifest baseline, emitting .forge-merge sidecars on conflict. "
            "'skip' preserves existing files unconditionally (pre-1.1 "
            "behaviour). 'overwrite' clobbers existing files with fragment "
            "content."
        ),
    )
    p.add_argument(
        "--plan-update",
        dest="plan_update",
        action="store_true",
        help=(
            "Preview the next --update without writing. Prints per-file "
            "decisions (applied / conflict / preserved) plus the list of "
            "fragments the next update would uninstall. Pair with --json "
            "for a machine-readable shape."
        ),
    )
    p.add_argument(
        "--remove-fragment",
        dest="remove_fragment",
        metavar="NAME",
        default=None,
        help=(
            "Disable a fragment by flipping its enabling option to its "
            "default value, then run --update so the uninstaller cleans "
            "up. Errors out when multiple options enable the fragment "
            "(disable each one explicitly with --set <path>=<default>)."
        ),
    )

    # Plan / dry-run — resolve and preview without writing.
    p.add_argument(
        "--plan",
        action="store_true",
        help=(
            "Resolve the config and print the ordered fragment plan + every "
            "planned mutation as a tree, then exit. Pairs with --json or --graph."
        ),
    )
    p.add_argument(
        "--graph",
        dest="plan_graph",
        action="store_true",
        help=(
            "When combined with --plan, emit a Mermaid dependency graph "
            "instead of the tree view. Useful for answering 'why is "
            "fragment X applied?' — pipe to a Mermaid renderer (mermaid-cli, "
            "GitHub-flavoured Markdown, mermaid.live)."
        ),
    )
    p.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        help="Run full generation to a tempdir but do not write to --output-dir.",
    )

    # Plugins
    p.add_argument(
        "--plugins",
        dest="plugins_subcommand",
        choices=["list"],
        metavar="SUBCMD",
        help="Plugin management: `list` shows discovered forge.plugins entry points.",
    )

    # Canvas
    p.add_argument(
        "--canvas",
        dest="canvas_subcommand",
        choices=["lint"],
        metavar="SUBCMD",
        help="Canvas component contract: `lint` validates a payload JSON against the manifest.",
    )
    p.add_argument(
        "--canvas-payload",
        metavar="FILE",
        help="Path to the canvas payload JSON for `forge --canvas lint`.",
    )

    # Doctor
    p.add_argument(
        "--doctor",
        action="store_true",
        help="Run environment diagnostics (Python/Node/Rust/Flutter toolchains, Docker, ports, forge.toml).",
    )

    # new-entity — add a CRUD entity YAML to the project.
    p.add_argument(
        "--new-entity-name",
        metavar="NAME",
        help="PascalCase entity name for `forge --new-entity-name Foo --new-entity-fields ...`",
    )
    p.add_argument(
        "--new-entity-fields",
        metavar="SPEC",
        help="Comma-separated field spec: 'name:string,qty:integer,status:enum:ItemStatus'",
    )

    # add-backend — scaffold an additional backend in an existing project.
    p.add_argument(
        "--add-backend-language",
        choices=["python", "node", "rust"],
        metavar="LANG",
        help="Language for the new backend with `forge --add-backend-language python --add-backend-name <name>`",
    )
    p.add_argument(
        "--add-backend-name",
        metavar="NAME",
        help="Service name for the new backend (ends up under `services/<name>/`)",
    )

    # preview — dry-run + diff against the configured output dir.
    p.add_argument(
        "--preview",
        action="store_true",
        help="Dry-run generation and print a unified diff against --output-dir. No files written.",
    )

    # migrate — umbrella codemod runner.
    p.add_argument(
        "--migrate",
        action="store_true",
        help="Run every applicable forge migration on the project at --project-path.",
    )
    p.add_argument(
        "--migrate-only",
        metavar="NAMES",
        help="Comma-separated migration names to run (skip the rest).",
    )
    p.add_argument(
        "--migrate-skip",
        metavar="NAMES",
        help="Comma-separated migration names to skip (run the rest).",
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
    p.add_argument(
        "--log-json",
        dest="log_json",
        action="store_true",
        help=(
            "Emit forge's own structured logs as NDJSON to stderr instead of "
            "the human-readable text format. Equivalent to setting "
            "FORGE_LOG_FORMAT=json. Useful for CI consumers and downstream "
            "log shippers."
        ),
    )
    p.add_argument(
        "--log-level",
        dest="log_level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default=None,
        help=(
            "Override the log level for forge's structured logger. "
            "Equivalent to FORGE_LOG_LEVEL=<level>. Defaults to INFO."
        ),
    )

    # Plugin-registered commands. Each is exposed as ``--<name>`` with
    # dest ``plugin_cmd_<name>`` (hyphens → underscores). Dispatch in
    # ``forge.cli.main`` walks the same registry and calls the handler
    # if the flag is set. Adding commands after parser construction
    # would require rebuilding every completion script, so we inject at
    # build time: ``forge.plugins.load_all()`` must have run first.
    _add_plugin_commands(p)

    return p


def _add_plugin_commands(parser: argparse.ArgumentParser) -> None:
    """Inject plugin-registered commands as ``--<name>`` flags."""
    try:
        from forge.plugins import COMMAND_REGISTRY  # noqa: PLC0415
    except ImportError:
        return
    for name in sorted(COMMAND_REGISTRY):
        flag = f"--{name}"
        dest = f"plugin_cmd_{name.replace('-', '_')}"
        # Only register if the flag isn't already claimed (avoid collisions
        # with core forge flags). Plugins should use namespaced names
        # like ``mycompany-audit`` to be safe.
        existing = {opt for action in parser._actions for opt in action.option_strings}
        if flag in existing:
            continue
        parser.add_argument(
            flag,
            dest=dest,
            action="store_true",
            help=f"[plugin command: {name}]",
        )


def _parse_args() -> argparse.Namespace:
    return _build_parser().parse_args()


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
