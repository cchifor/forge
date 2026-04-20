"""Shell completion script generation.

Completion scripts are generated once at module load by introspecting
the parser returned by ``_build_parser()``. Every flag registered in
argparse is guaranteed to appear in every shell's script, so adding /
renaming / removing a flag updates completions automatically. Tests in
``tests/test_cli_completion.py`` assert this parity.
"""

from __future__ import annotations

import argparse
import sys

from forge.cli.parser import _build_parser


def _flag_actions(parser: argparse.ArgumentParser) -> list[argparse.Action]:
    """Every option-bearing action on the parser, in registration order.

    Includes argparse's auto-added ``-h / --help``.
    """
    return [a for a in parser._actions if a.option_strings]


def _action_help_short(action: argparse.Action) -> str:
    """Short (first-sentence) help text for a completion tooltip."""
    text = action.help or action.dest.replace("_", " ")
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
