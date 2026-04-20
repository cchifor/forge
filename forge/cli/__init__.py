"""Backward-compatible re-exports for the old monolithic ``forge.cli``.

The real modules are ``forge.cli.parser``, ``forge.cli.completion``,
``forge.cli.loader``, ``forge.cli.builder``, ``forge.cli.interactive``,
``forge.cli.main``, and ``forge.cli.commands.*``. This ``__init__`` re-
exports every private helper the original single-file CLI exposed so
existing tests (``tests/test_cli_*.py``) that import from ``forge.cli``
continue to work unchanged.
"""

from __future__ import annotations

# Keep the questionary module available at ``forge.cli.questionary`` for
# tests that patch ``forge.cli.questionary.text`` and friends.
import questionary  # noqa: F401

from forge.cli.builder import (
    _Resolver,
    _build_backends_from_cfg,
    _build_config,
    _build_frontend_from_cfg,
    _build_options,
    _coerce_set_value,
    _flatten_nested,
    _normalize_features,
)
from forge.cli.commands.describe import _describe_option
from forge.cli.commands.list import (
    _build_option_rows,
    _description_cell,
    _dispatch_list,
    _format_json,
    _format_text,
    _format_yaml,
    _option_backends,
    _wrap_cols,
)
from forge.cli.commands.schema import _dispatch_schema
from forge.cli.commands.update import _run_update
from forge.cli.completion import (
    _BASH_COMPLETION,
    _COMPLETIONS,
    _FISH_COMPLETION,
    _PARSER_FOR_COMPLETION,
    _ZSH_COMPLETION,
    _action_help_short,
    _action_path_kind,
    _bash_completion_script,
    _fish_completion_script,
    _flag_actions,
    _metavar_str,
    _print_completion,
    _zsh_completion_script,
)
from forge.cli.interactive import (
    _ask_confirm,
    _ask_features,
    _ask_port,
    _ask_select,
    _ask_text,
    _collect_inputs,
    _parse_features,
    _print_summary,
    _prompt_backend,
)
from forge.cli.loader import _load_config_file
from forge.cli.main import _json_error, main
from forge.cli.parser import COLOR_SCHEMES, FRAMEWORK_MAP, _build_parser, _is_headless, _parse_args

# Tests patch ``forge.cli.generate`` — re-export the module-local name.
from forge.generator import generate  # noqa: F401

__all__ = [
    "COLOR_SCHEMES",
    "FRAMEWORK_MAP",
    "_BASH_COMPLETION",
    "_COMPLETIONS",
    "_FISH_COMPLETION",
    "_PARSER_FOR_COMPLETION",
    "_Resolver",
    "_ZSH_COMPLETION",
    "_action_help_short",
    "_action_path_kind",
    "_ask_confirm",
    "_ask_features",
    "_ask_port",
    "_ask_select",
    "_ask_text",
    "_bash_completion_script",
    "_build_backends_from_cfg",
    "_build_config",
    "_build_frontend_from_cfg",
    "_build_option_rows",
    "_build_options",
    "_build_parser",
    "_coerce_set_value",
    "_collect_inputs",
    "_describe_option",
    "_description_cell",
    "_dispatch_list",
    "_dispatch_schema",
    "_fish_completion_script",
    "_flag_actions",
    "_flatten_nested",
    "_format_json",
    "_format_text",
    "_format_yaml",
    "_is_headless",
    "_json_error",
    "_load_config_file",
    "_metavar_str",
    "_normalize_features",
    "_option_backends",
    "_parse_args",
    "_parse_features",
    "_print_completion",
    "_print_summary",
    "_prompt_backend",
    "_run_update",
    "_wrap_cols",
    "_zsh_completion_script",
    "generate",
    "main",
    "questionary",
]
