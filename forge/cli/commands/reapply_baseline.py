"""``forge --reapply-baseline`` — discard user edits to fragment-owned records.

Equivalent to ``forge --update --mode overwrite`` scoped to the records
that are currently classified ``user-modified`` against the
``forge.toml`` baselines.

The CLI dispatcher resolves the project root, hands off to
:func:`forge.sync.forge_to_project.reapply_baseline.reapply_baseline`,
renders the report (human or JSON), and maps the report's verdict to a
process exit code:

* ``0`` — every selected record reset cleanly (or skipped as unchanged
  / not-fragment).
* ``5`` — at least one record errored (sentinel-corrupt, missing
  fragment in registry, write failure) OR the project's ``forge.toml``
  is missing / malformed. Mirrors the manifest-IO code the rest of the
  CLI uses for provenance failures.

The verb is intentionally distinct from ``--update``: it doesn't run
the resolver, doesn't touch base-template files, and isn't gated on
``--mode``. It's the targeted escape hatch for "throw away my local
edits to the fragment-emitted lane".
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from forge import telemetry
from forge.sync.forge_to_project.reapply_baseline import reapply_baseline

# Exit code for run-level / per-record failures. Mirrors the rest of
# the CLI taxonomy (5 = manifest / provenance IO failure).
_EXIT_ERROR = 5


def _run_reapply_baseline(args: argparse.Namespace) -> int:
    """Dispatch ``forge --reapply-baseline``. Returns the exit code.

    Resolves ``--project-path`` (defaulting to the current directory)
    and the optional ``--reapply-scope`` (defaulting to both kinds),
    invokes :func:`reapply_baseline`, prints the report in JSON or
    human shape, and returns the exit code per the module docstring.
    Never raises — every failure path surfaces as a non-zero return.
    """
    project_root = Path(getattr(args, "project_path", ".") or ".").resolve()
    quiet = bool(getattr(args, "quiet", False)) or bool(getattr(args, "json_output", False))
    json_output = bool(getattr(args, "json_output", False))
    dry_run = bool(getattr(args, "dry_run", False))

    scope_arg = getattr(args, "reapply_scope", None)
    scope: tuple[str, ...]
    if scope_arg:
        scope = tuple(s.strip() for s in str(scope_arg).split(",") if s.strip())
    else:
        scope = ("files", "blocks")

    report = reapply_baseline(
        project_root,
        scope=scope,
        dry_run=dry_run,
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
        telemetry.EVENT_REAPPLY_BASELINE_RAN,
        project_root=project_root,
        entries_by_action=entries_by_action,
        entry_count=len(report.entries),
        accepted=report.reset_count,
        skipped=report.skipped_count,
        errored=report.error_count,
    )

    # Run-level errors (missing forge.toml, malformed TOML) trip the
    # exit signal — same code the rest of the CLI uses for manifest /
    # provenance IO failures. Per-record errors trip the same signal
    # because the operator deserves a non-zero exit when the verb
    # couldn't fully complete its requested work.
    if report.errors or report.error_count > 0:
        return _EXIT_ERROR
    return 0
