"""`forge --update` — re-apply options to an existing forge-generated project."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import cast

from forge import telemetry
from forge.fragment_context import UpdateMode


def _run_update(args: argparse.Namespace) -> None:
    """Run `forge update` against the given project and exit."""
    from forge.errors import GeneratorError as _GeneratorError  # noqa: PLC0415
    from forge.sync.forge_to_project.updater import update_project  # noqa: PLC0415

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

    _emit_update_telemetry(project_path, summary)
    sys.exit(0)


def _emit_update_telemetry(project_path: Path, summary: dict) -> None:
    """Emit ``update.ran`` plus per-conflict ``update.conflict_emitted``.

    Aggregate fields (``files_applied``, ``blocks_applied``,
    ``conflicts``) survive the ``minimal`` field filter; the
    per-conflict events carry the sidecar path which ``minimal`` mode
    redacts.
    """
    fragments_applied = cast("list[str]", summary.get("fragments_applied", []) or [])
    file_conflicts = int(cast("int", summary.get("file_conflicts", 0) or 0))
    user_modified = int(cast("int", summary.get("user_modified_count", 0) or 0))
    uninstalled = summary.get("uninstalled", []) or []

    telemetry.emit(
        telemetry.EVENT_UPDATE_RAN,
        project_root=project_path,
        files_applied=len(fragments_applied),
        blocks_applied=user_modified,
        conflicts=file_conflicts,
        entry_count=len(fragments_applied),
        mode=str(summary.get("update_mode", "")),
        uninstalled=len(uninstalled),
    )
    # We don't have per-sidecar metadata in the summary today; the
    # update_project return value carries the count only. A future PR can
    # extend ``update_project`` to yield per-conflict shapes — until then
    # we emit one conflict event per sidecar count for symmetry with
    # harvest's per-candidate events.
    for _ in range(file_conflicts):
        telemetry.emit(
            telemetry.EVENT_UPDATE_CONFLICT,
            project_root=project_path,
            kind="file",
            action="conflict",
        )
