"""CLI entry point — dispatches flags to command handlers.

``main()`` is referenced as the console_script entry point from
``pyproject.toml``. It parses args, dispatches introspection commands
(--list / --schema / --describe / --update / --completion / --plugins /
--plan), then either runs headless generation from a config or drops
into interactive mode.
"""

from __future__ import annotations

import json
import os
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
from forge.errors import (
    FilesystemError,
    ForgeError,
    InjectionError,
    MergeError,
    PluginError,
    ProvenanceError,
    TemplateError,
)
from forge.generator import generate


def _exit_code_for(err: ForgeError) -> int:
    """Map a :class:`ForgeError` subclass to a CLI exit code.

    2 — generic failure (options / fragment / generator)
    3 — injection failure
    4 — merge conflict (non-recoverable)
    5 — provenance / manifest IO failure
    6 — plugin load / registration failure
    7 — template render / jinja / not-found failure
    8 — filesystem IO failure
    """
    if isinstance(err, InjectionError):
        return 3
    if isinstance(err, MergeError):
        return 4
    if isinstance(err, ProvenanceError):
        return 5
    if isinstance(err, PluginError):
        return 6
    if isinstance(err, TemplateError):
        return 7
    if isinstance(err, FilesystemError):
        return 8
    return 2


def _json_error(stdout_fd, err: object) -> None:
    """Write a JSON error envelope to the real stdout and exit.

    Accepts either a :class:`ForgeError` (emits full ``{error, code, hint,
    context}``) or a plain string / exception (emits ``{error: str(msg)}``
    for backward compat with legacy callers that hit ``ValueError`` /
    ``KeyError`` on config parsing).
    """
    if isinstance(err, ForgeError):
        payload = err.as_envelope()
        exit_code = _exit_code_for(err)
    else:
        payload = {"error": str(err)}
        exit_code = 2
    stdout_fd.write(json.dumps(payload) + "\n")
    stdout_fd.flush()
    sys.exit(exit_code)


def main() -> None:
    # Install the structured logging handler before anything else so
    # plugin-load events flow through it. Honors FORGE_LOG_FORMAT and
    # FORGE_LOG_LEVEL environment variables, plus the --log-json /
    # --log-level CLI flags via a pre-parse scan (the real argparse pass
    # happens after plugins.load_all() so plugin commands can extend it).
    from forge.logging import configure_logging  # noqa: PLC0415

    early_fmt = "json" if "--log-json" in sys.argv[1:] else None
    early_level: str | None = None
    for i, token in enumerate(sys.argv[1:]):
        if token == "--log-level" and i + 2 <= len(sys.argv) - 1:
            early_level = sys.argv[i + 2]
            break
        if token.startswith("--log-level="):
            early_level = token.split("=", 1)[1]
            break
    configure_logging(level=early_level, fmt=early_fmt)

    # Discover third-party plugins before parsing — lets them extend the
    # argparse surface and the option registry before args hit validation.
    from forge import plugins  # noqa: PLC0415

    plugins.load_all()

    # Epic 3 (plugin SDK MVP) — surface plugin-load failures at every
    # CLI entry point, not only via ``forge --plugins list``. Otherwise
    # a broken plugin produces confusing "fragment not found" errors
    # later in generation with no hint that a plugin failed earlier.
    # Suppressible via ``FORGE_QUIET_PLUGIN_WARNINGS=1`` for scripts
    # that intentionally tolerate broken plugins.
    if plugins.FAILED_PLUGINS and os.environ.get("FORGE_QUIET_PLUGIN_WARNINGS") != "1":
        for name, reason in plugins.FAILED_PLUGINS:
            print(
                f"  [warn] plugin {name!r} failed to load: {reason}",
                file=sys.stderr,
            )
        print(
            "  [warn] Run `forge --plugins list` for plugin status; "
            "set FORGE_QUIET_PLUGIN_WARNINGS=1 to suppress.",
            file=sys.stderr,
        )

    args = _parse_args()

    # Re-apply if argparse normalised the values (e.g. uppercase level).
    # Idempotent: configure_logging replaces the forge-owned handler.
    if getattr(args, "log_json", False) or getattr(args, "log_level", None):
        configure_logging(
            level=getattr(args, "log_level", None),
            fmt="json" if getattr(args, "log_json", False) else None,
        )

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

    if getattr(args, "plan_update", False):
        from forge.cli.commands.plan_update import _run_plan_update  # noqa: PLC0415

        _run_plan_update(args)

    if getattr(args, "remove_fragment", None):
        from forge.cli.commands.remove_fragment import _run_remove_fragment  # noqa: PLC0415

        _run_remove_fragment(args)

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
    except ForgeError as e:
        if getattr(args, "json_output", False):
            _json_error(_real_stdout, e)
        print(f"\n  Generation failed: {e}", file=sys.stderr)
        if e.hint:
            print(f"  Hint: {e.hint}", file=sys.stderr)
        sys.exit(_exit_code_for(e))

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
