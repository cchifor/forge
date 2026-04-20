"""CLI entry point — dispatches flags to command handlers.

``main()`` is referenced as the console_script entry point from
``pyproject.toml``. It parses args, dispatches introspection commands
(--list / --schema / --describe / --update / --completion / --plugins /
--plan), then either runs headless generation from a config or drops
into interactive mode.
"""

from __future__ import annotations

import json
import sys
from typing import Any

from forge.cli import interactive as _interactive
from forge.cli.builder import _build_config
from forge.cli.commands.describe import _describe_option
from forge.cli.commands.list import _dispatch_list
from forge.cli.commands.schema import _dispatch_schema
from forge.cli.commands.update import _run_update
from forge.cli.completion import _print_completion
from forge.cli.loader import _load_config_file
from forge.cli.parser import _is_headless, _parse_args
from forge.config import FrontendFramework, ProjectConfig
from forge.docker_manager import boot
from forge.errors import GeneratorError
from forge.generator import generate


def _json_error(stdout_fd, message: str) -> None:
    """Write a JSON error object to the real stdout and exit."""
    stdout_fd.write(json.dumps({"error": message}) + "\n")
    stdout_fd.flush()
    sys.exit(2)


def main() -> None:
    # Discover third-party plugins before parsing — lets them extend the
    # argparse surface and the option registry before args hit validation.
    from forge import plugins  # noqa: PLC0415

    plugins.load_all()

    args = _parse_args()

    if getattr(args, "list", False):
        fmt = getattr(args, "format", None) or "text"
        _dispatch_list(fmt)

    if getattr(args, "schema", False):
        _dispatch_schema()

    if getattr(args, "describe", None):
        _describe_option(args.describe)

    if getattr(args, "plugins_subcommand", None):
        from forge.cli.commands.plugins import _dispatch_plugins  # noqa: PLC0415

        _dispatch_plugins(args.plugins_subcommand, json_output=getattr(args, "json_output", False))

    if getattr(args, "canvas_subcommand", None):
        from forge.cli.commands.canvas import _dispatch_canvas  # noqa: PLC0415

        _dispatch_canvas(
            args.canvas_subcommand,
            payload_path=getattr(args, "canvas_payload", None),
        )

    if getattr(args, "doctor", False):
        from forge.doctor import _dispatch_doctor  # noqa: PLC0415

        _dispatch_doctor(
            project_path=getattr(args, "project_path", "."),
            json_output=getattr(args, "json_output", False),
        )

    if getattr(args, "new_entity_name", None):
        from forge.cli.commands.new_entity import _dispatch_new_entity  # noqa: PLC0415

        _dispatch_new_entity(args)

    if getattr(args, "add_backend_language", None):
        from forge.cli.commands.add_backend import _dispatch_add_backend  # noqa: PLC0415

        _dispatch_add_backend(args)

    if getattr(args, "preview", False):
        from forge.cli.commands.preview import _dispatch_preview  # noqa: PLC0415

        _dispatch_preview(args)

    if getattr(args, "migrate", False):
        from forge.cli.commands.migrate import _dispatch_migrate  # noqa: PLC0415

        _dispatch_migrate(args)

    if getattr(args, "plan", False):
        from forge.cli.commands.plan import _dispatch_plan  # noqa: PLC0415

        _dispatch_plan(args)

    if getattr(args, "update", False):
        _run_update(args)

    if getattr(args, "completion", None):
        _print_completion(args.completion)

    # Plugin-registered commands — walk the registry and invoke any flag
    # the user set. Handlers return an int exit code we pass to sys.exit.
    from forge.plugins import COMMAND_REGISTRY  # noqa: PLC0415

    for name, handler in COMMAND_REGISTRY.items():
        dest = f"plugin_cmd_{name.replace('-', '_')}"
        if getattr(args, dest, False):
            code = handler(args)
            sys.exit(int(code) if isinstance(code, int) else 0)

    # When --json is set, redirect all print() to stderr so stdout is clean JSON
    _real_stdout = sys.stdout
    if getattr(args, "json_output", False):
        sys.stdout = sys.stderr

    config: ProjectConfig
    if _is_headless(args):
        try:
            cfg = _load_config_file(args.config) if args.config else {}
        except ValueError as e:
            if getattr(args, "json_output", False):
                _json_error(_real_stdout, str(e))
            print(f"  Configuration error: {e}", file=sys.stderr)
            sys.exit(2)

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
            _interactive._print_summary(config)

        if not args.yes and not _interactive._ask_confirm("Proceed with generation?"):
            print("\n  Aborted.")
            sys.exit(0)
    else:
        collected = _interactive._collect_inputs()
        if collected is None:
            print("\n  Aborted.")
            sys.exit(0)
        config = collected

    quiet = (args.quiet or getattr(args, "json_output", False)) and not getattr(
        args, "verbose", False
    )

    if not quiet:
        print()
    try:
        dry_run = bool(getattr(args, "dry_run", False))
        project_root = generate(config, quiet=quiet, dry_run=dry_run)
    except TypeError:
        # generate() older signature (no dry_run kwarg) — fall back.
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

    if not args.no_docker and config.backend is not None and not getattr(args, "dry_run", False):
        if args.yes:
            boot(project_root)
        else:
            print()
            if _interactive._ask_confirm("Start Docker Compose stack?", default=False):
                boot(project_root)
