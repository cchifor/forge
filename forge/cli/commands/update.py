"""`forge --update` — re-apply options to an existing forge-generated project."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import cast

from forge.fragment_context import UpdateMode


def _run_update(args: argparse.Namespace) -> None:
    """Run `forge update` against the given project and exit."""
    from forge.errors import GeneratorError as _GeneratorError  # noqa: PLC0415
    from forge.updater import update_project  # noqa: PLC0415

    project_path = Path(getattr(args, "project_path", ".")).resolve()
    quiet = bool(getattr(args, "quiet", False))
    update_mode = cast("UpdateMode", getattr(args, "update_mode", "merge"))

    if not quiet:
        print(f"forge update: {project_path} (mode={update_mode})")
    try:
        summary = update_project(project_path, quiet=quiet, update_mode=update_mode)
    except _GeneratorError as exc:
        if getattr(args, "json_output", False):
            print(json.dumps({"error": str(exc)}))
        else:
            print(f"error: {exc}", file=sys.stderr)
        sys.exit(2)

    if getattr(args, "json_output", False):
        print(json.dumps(summary, indent=2))
    elif not quiet:
        before = summary["forge_version_before"]
        after = summary["forge_version_after"]
        backends = cast("list[str]", summary["backends"])
        fragments_applied = cast("list[str]", summary["fragments_applied"])
        file_conflicts = int(cast("int", summary.get("file_conflicts", 0)))
        frags = ", ".join(fragments_applied) or "(none)"
        print(f"  forge {before} -> {after}")
        print(f"  backends: {', '.join(backends)}")
        print(f"  fragments: {frags}")
        if file_conflicts:
            print(f"  file conflicts: {file_conflicts} — resolve .forge-merge sidecar(s) by hand.")
        print("Update complete.")
    sys.exit(0)
