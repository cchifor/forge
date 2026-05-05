"""``forge --plan-update`` — preview the next ``forge --update`` (P1.2)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import cast


def _run_plan_update(args: argparse.Namespace) -> None:
    """Compute and print a dry-run plan for ``forge --update``."""
    from forge.errors import GeneratorError as _GeneratorError  # noqa: PLC0415
    from forge.fragment_context import UpdateMode  # noqa: PLC0415
    from forge.plan_update import plan_update  # noqa: PLC0415

    project_path = Path(getattr(args, "project_path", ".")).resolve()
    quiet = bool(getattr(args, "quiet", False))
    update_mode = cast("UpdateMode", getattr(args, "update_mode", "merge"))
    json_output = bool(getattr(args, "json_output", False))

    try:
        report = plan_update(project_path, update_mode=update_mode)
    except _GeneratorError as exc:
        if json_output:
            print(json.dumps({"error": str(exc)}))
        else:
            print(f"error: {exc}", file=sys.stderr)
        sys.exit(2)

    if json_output:
        print(json.dumps(report.as_dict(), indent=2))
        sys.exit(0)

    if not quiet:
        print(f"forge --plan-update: {project_path} (mode={update_mode})")
        print(f"  backends: {', '.join(report.backends)}")
        if report.fragments_to_uninstall:
            print(f"  fragments to uninstall: {', '.join(report.fragments_to_uninstall)}")
        print(f"  files inspected: {len(report.file_decisions)}")
        if report.applied_count:
            print(f"  would apply: {report.applied_count}")
        if report.conflict_count:
            print(f"  would conflict: {report.conflict_count}")

        # Per-action summary listing. Skip the noisy ``skipped-idempotent``
        # bucket unless verbose so the common case (no changes) doesn't
        # spam the terminal; --verbose is reserved for future implementation.
        for entry in report.file_decisions:
            if entry.action == "skipped-idempotent":
                continue
            print(
                f"    [{entry.action}] {entry.rel_path}  "
                f"({entry.fragment} / {entry.backend}) — {entry.reason}"
            )

    sys.exit(0)
