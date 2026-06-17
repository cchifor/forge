"""``forge --resolve`` — interactive ``.forge-merge`` sidecar walk.

The canonical "after-conflict" workflow: ``forge --update`` produces
``.forge-merge`` / ``.forge-merge.bin`` sidecars for every record whose
three-way decide returned ``conflict``. ``forge --resolve`` walks
those sidecars and prompts the operator per sidecar:

* ``accept``  — apply the sidecar's content to the target; delete the
                sidecar; re-stamp the manifest baseline.
* ``reject``  — delete the sidecar; preserve the target as-is;
                re-stamp the baseline to the current on-disk body
                (so the user's edit becomes the new baseline).
* ``edit``    — open ``$EDITOR`` on a 3-way conflict scratch file;
                apply the user's hand-merge to the target.
* ``skip``    — leave both files alone; continue.
* ``quit``    — stop the walk; mark remaining sidecars as skipped.

This dispatcher resolves the project root, hands off to
:func:`forge.sync.forge_to_project.resolver.resolve_sidecars`, renders
the report (human or JSON), and maps the report's verdict to a
process exit code:

* ``0`` — walk completed without per-sidecar errors. An empty project
  (no sidecars) is still a clean exit.
* ``5`` — project root missing / unreadable, or per-sidecar errors
  surfaced (matches the manifest-IO code the rest of the CLI uses).

Mirrors the dispatch shape of
:mod:`forge.cli.commands.verify` /
:mod:`forge.cli.commands.harvest` /
:mod:`forge.cli.commands.accept_harvested` so the CLI surface stays
consistent.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from forge import telemetry
from forge.sync.forge_to_project.resolver import resolve_sidecars

# Exit code when the project root is missing / unreadable, or when any
# per-sidecar entry surfaced as ``action="error"``. Mirrors the other
# CLI verbs' "operator should fix the input" code so CI gates that
# already key on 5 cover the new failure modes.
_EXIT_RESOLVE_FAILURE = 5


def _run_resolve(args: argparse.Namespace) -> int:
    """Dispatch ``forge --resolve``. Returns the exit code.

    Resolves ``--resolve-path`` (falling back to ``--project-path``,
    then the current directory), invokes
    :func:`resolve_sidecars`, prints the report in JSON or human
    shape, and returns 0 on success or 5 on failure. Never raises —
    every failure path surfaces as a non-zero return.
    """
    resolve_path_arg = getattr(args, "resolve_path", None)
    if resolve_path_arg:
        project_root = Path(resolve_path_arg).resolve()
    else:
        project_root = Path(getattr(args, "project_path", ".") or ".").resolve()

    quiet = bool(getattr(args, "quiet", False)) or bool(getattr(args, "json_output", False))
    json_output = bool(getattr(args, "json_output", False))

    # HF-3 follow-up: refuse to prompt when stdin isn't a TTY and there
    # are sidecars to walk. resolve_sidecars -> _prompt_action ->
    # _ask_select calls questionary which exits 1 with no structured
    # output when stdin is closed — agents driving forge --resolve --json
    # would otherwise see an empty failure they can't classify.
    # No sidecars means no prompts will fire, so the empty-project path
    # is still allowed (returns a clean report with no entries).
    # Discovery reuses ``_discover_sidecars`` so a directory whose name
    # ends in ``.forge-merge`` can't trigger a false-positive refusal —
    # the same filter the walker uses (is_file + suffix match).
    if not sys.stdin.isatty():
        from forge.sync.forge_to_project.resolver._sidecar_parser import (  # noqa: PLC0415
            _discover_sidecars,
        )

        sidecars = _discover_sidecars(project_root)
        if sidecars:
            msg = (
                f"Found {len(sidecars)} unresolved sidecar(s) but stdin is "
                "not a TTY. forge --resolve is interactive — re-run in a "
                "terminal or accept/reject the sidecars by hand."
            )
            if json_output:
                sys.stdout.write(json.dumps({"error": msg, "sidecar_count": len(sidecars)}) + "\n")
            else:
                sys.stderr.write(f"forge --resolve: {msg}\n")
            return _EXIT_RESOLVE_FAILURE

    # Initiative #6 (caching): parse forge.toml once per invocation.
    from forge.sync._manifest_cache import manifest_cache_scope  # noqa: PLC0415

    try:
        with manifest_cache_scope():
            report = resolve_sidecars(project_root, quiet=quiet)
    except FileNotFoundError as exc:
        # Project root missing — surface a structured error so JSON
        # consumers can branch on a known shape, then exit with the
        # failure code (5).
        if json_output:
            sys.stdout.write(json.dumps({"error": str(exc)}) + "\n")
        else:
            sys.stderr.write(f"forge --resolve: {exc}\n")
        return _EXIT_RESOLVE_FAILURE

    if json_output:
        sys.stdout.write(json.dumps(report.to_dict(), indent=2) + "\n")
    else:
        report.render_human(sys.stdout)

    entries_by_action: dict[str, int] = {}
    for e in report.entries:
        entries_by_action[e.action] = entries_by_action.get(e.action, 0) + 1
    telemetry.emit(
        telemetry.EVENT_RESOLVE_RAN,
        project_root=project_root,
        entries_by_action=entries_by_action,
        entry_count=len(report.entries),
        accepted=report.accepted,
        rejected=report.rejected,
        edited=report.edited,
        skipped=report.skipped,
        errored=report.error_count,
    )

    # Per-sidecar errors trip the failure exit code. Project-level
    # errors do too (currently empty — handled via FileNotFoundError
    # above — but kept for symmetry with the other verbs).
    if report.errors or report.error_count > 0:
        return _EXIT_RESOLVE_FAILURE
    return 0
