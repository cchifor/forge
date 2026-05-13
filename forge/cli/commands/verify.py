"""``forge --verify`` — read-only drift detection vs. forge.toml baselines.

The CLI dispatcher resolves the project root, hands off to
:func:`forge.verify.verify_project`, renders the report (human or JSON),
and maps the report's verdict to a process exit code:

* ``0`` — clean (or any verdict when ``--fail-on=never``).
* ``10`` — drift detected (user-modified / missing records) and
  ``--fail-on`` includes drift.
* ``11`` — conflict detected (sentinel-corrupt records).
* ``5`` — manifest missing or unreadable (same code the rest of the CLI
  uses for provenance / manifest IO failures).

The verb is intentionally separated from generation flow: ``--verify``
never raises a :class:`forge.errors.ForgeError`; missing-manifest is
the only translation back to ``_exit_code_for``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from forge.errors import EXIT_VERIFY_CONFLICT, EXIT_VERIFY_DRIFT
from forge.verify import VerifyFailOn, VerifyReport, verify_project

# Exit code for the manifest-missing path. The rest of the CLI maps
# :class:`forge.errors.ProvenanceError` to 5 via ``_exit_code_for``;
# we mirror that here so the verb's exit codes stay consistent with
# the broader CLI taxonomy.
_EXIT_MANIFEST_MISSING = 5


def _run_verify(args: argparse.Namespace) -> int:
    """Dispatch ``forge --verify``. Returns the exit code.

    Resolves ``--project-path`` (defaulting to the current directory),
    invokes :func:`forge.verify.verify_project`, prints the report in
    JSON or human shape, and returns the exit code via
    :func:`_verify_exit_code`. Never raises — every failure path
    surfaces as a non-zero return.
    """
    project_root = Path(getattr(args, "project_path", ".") or ".").resolve()
    scope = getattr(args, "verify_scope", "all")
    fail_on: VerifyFailOn = getattr(args, "verify_fail_on", "drift")
    json_output = bool(getattr(args, "json_output", False))

    try:
        report = verify_project(project_root, scope=scope, fail_on=fail_on)
    except FileNotFoundError:
        # No forge.toml at project root. Surface a structured error so
        # JSON consumers can branch on a known shape, then exit with the
        # manifest-missing code (5) — same as the rest of the CLI.
        if json_output:
            sys.stdout.write(json.dumps({"error": f"no forge.toml at {project_root}"}) + "\n")
        else:
            sys.stderr.write(f"forge --verify: no forge.toml at {project_root}\n")
        return _EXIT_MANIFEST_MISSING

    if json_output:
        sys.stdout.write(json.dumps(report.to_dict(), indent=2) + "\n")
    else:
        report.render_human(sys.stdout)

    return _verify_exit_code(report, fail_on)


def _verify_exit_code(report: VerifyReport, fail_on: VerifyFailOn) -> int:
    """Translate a :class:`VerifyReport.worst` value to a process exit code.

    Truth table:

    +----------------+-----------+--------+------+
    | report.worst   | fail_on   | result | code |
    +================+===========+========+======+
    | clean          | (any)     | pass   | 0    |
    | drift          | never     | pass   | 0    |
    | drift          | conflict  | pass   | 0    |
    | drift          | drift     | drift  | 10   |
    | conflict       | never     | pass   | 0    |
    | conflict       | conflict  | conflict | 11 |
    | conflict       | drift     | conflict | 11 |
    +----------------+-----------+--------+------+

    ``conflict`` is strictly more severe than ``drift``: when
    ``fail_on=drift`` and the report turns up sentinel corruption, the
    caller still gets the conflict exit code (11) rather than 10 — the
    code identifies *what* failed, not *what triggered* the fail.
    """
    if fail_on == "never":
        return 0
    if report.worst == "clean":
        return 0
    if report.worst == "conflict":
        # Conflicts always exit 11 when fail_on isn't "never" —
        # higher-severity wins over the threshold knob.
        return EXIT_VERIFY_CONFLICT
    # report.worst == "drift" here
    if fail_on == "drift":
        return EXIT_VERIFY_DRIFT
    # fail_on == "conflict" and worst is drift → drift alone passes.
    return 0
