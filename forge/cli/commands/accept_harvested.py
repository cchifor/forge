"""``forge --accept-harvested`` — close the Story B round-trip (Phase 6).

After the user's ``forge --harvest`` bundle has been reviewed and
landed upstream (via ``--emit-pr`` or by hand), this verb re-stamps
the project's ``forge.toml`` so the user's edits become the new
manifest baseline. Without this step, every subsequent
``forge --verify`` would re-classify the user's blocks as
``user-modified`` against the now-upstream fragment baseline and
every ``forge --update`` would emit ``.forge-merge`` sidecars.

This is the symmetric closing verb to ``--harvest``:

* ``forge --harvest`` → bundle on disk (forward extract).
* (User lands the upstream PR via ``--emit-pr`` or by hand.)
* ``forge --accept-harvested`` → manifest re-stamped (reverse close).

The CLI dispatcher resolves the project root + bundle path, hands off
to :func:`accept_harvested`, renders the report (human or JSON), and
maps the report's verdict to a process exit code:

* ``0`` — bundle accepted (whether or not any candidates re-stamped).
  An empty bundle is still a clean exit — running the verb on a
  cancelled / unused bundle should be a quiet no-op, not a failure.
* ``5`` — bundle or project's ``forge.toml`` missing / malformed.
  Mirrors the manifest-IO code the rest of the CLI uses for
  provenance failures.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from forge import telemetry
from forge.sync.project_to_forge.accept import accept_harvested

# Exit code when the bundle / manifest can't be opened. Mirrors the
# ``--verify`` / ``--harvest`` dispatchers so the accept verb's exit
# codes stay consistent with the broader CLI taxonomy
# (5 = manifest / provenance IO failure).
_EXIT_MANIFEST_MISSING = 5


def _run_accept_harvested(args: argparse.Namespace) -> int:
    """Dispatch ``forge --accept-harvested BUNDLE``. Returns the exit code.

    Resolves ``--project-path`` (defaulting to the current directory)
    and the positional bundle path given on ``--accept-harvested``,
    invokes :func:`accept_harvested`, prints the report in JSON or
    human shape, and returns 0 on success or 5 on bundle-level
    failure. Never raises — every failure path surfaces as a non-zero
    return.
    """
    bundle_arg = getattr(args, "accept_harvested", None)
    if not bundle_arg:
        # The CLI parser declares ``metavar="BUNDLE"`` for the flag, so
        # argparse should never deliver an empty value here. Defensive
        # check kept so a hand-built Namespace (tests) gets a clear
        # error rather than a confusing path-resolution crash.
        sys.stderr.write("forge --accept-harvested: missing bundle path argument\n")
        return _EXIT_MANIFEST_MISSING

    bundle_path = Path(bundle_arg).resolve()
    project_root = Path(getattr(args, "project_path", ".") or ".").resolve()
    quiet = bool(getattr(args, "quiet", False)) or bool(getattr(args, "json_output", False))
    json_output = bool(getattr(args, "json_output", False))

    risk_filter_arg = getattr(args, "accept_risk_filter", None)
    risk_filter: tuple[str, ...] = (
        tuple(s.strip() for s in str(risk_filter_arg).split(",") if s.strip())
        if risk_filter_arg
        else ("safe-apply",)
    )

    report = accept_harvested(
        project_root=project_root,
        bundle_path=bundle_path,
        risk_filter=risk_filter,
        quiet=quiet,
    )

    if json_output:
        sys.stdout.write(json.dumps(report.to_dict(), indent=2) + "\n")
    else:
        report.render_human(sys.stdout)

    entries_by_action: dict[str, int] = {}
    for e in report.entries:
        entries_by_action[e.action] = entries_by_action.get(e.action, 0) + 1
    telemetry.emit(
        telemetry.EVENT_ACCEPT_HARVESTED_RAN,
        project_root=project_root,
        entries_by_action=entries_by_action,
        entry_count=len(report.entries),
        accepted=report.restamped,
        skipped=report.skipped,
        errored=report.errored,
    )

    # Bundle-level errors (missing manifest.json, malformed forge.toml,
    # etc.) map to the manifest-IO exit code — same as ``--verify`` /
    # ``--harvest``. Per-candidate ``error`` entries do NOT trip this
    # signal; they're surfaced in the report instead. The rationale:
    # a partial-failure accept is still a usable result, but a missing
    # bundle is a config-time error the operator should fix.
    if report.errors:
        return _EXIT_MANIFEST_MISSING
    return 0
