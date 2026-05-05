"""Codemod: replace hand-written UI-protocol types with generated ones.

Before 1.0.0a1, Vue / Svelte / Flutter templates shipped hand-authored
``types.ts`` / ``chat.types.ts`` / ``agent_state.dart`` for the agentic-UI
protocol. The 1.0.0a1 codegen pipeline emits those same types from
``forge/templates/_shared/ui-protocol/*.schema.json``.

This migration:

  1. Detects legacy hand-written files in their historical locations.
  2. Renames them to ``<name>.legacy`` so the user can diff and pull over
     any custom additions.
  3. Re-runs the codegen pipeline to emit authoritative versions.

Safe on repeat: files already renamed or absent are skipped silently.
"""

from __future__ import annotations

from pathlib import Path

from forge.migrations.base import MigrationReport

NAME = "ui-protocol"
FROM = "0.x"
TO = "1.0.0a1"
DESCRIPTION = "Retire hand-written UI-protocol types; regenerate from shared schemas."

_LEGACY_TARGETS = [
    # (relative-path, description)
    ("apps/*/src/features/ai_chat/types.ts", "Vue hand-written protocol types"),
    ("apps/*/src/lib/features/chat/chat.types.ts", "Svelte hand-written protocol types"),
    (
        "apps/*/lib/src/features/chat/domain/agent_state.dart",
        "Flutter hand-written protocol types",
    ),
    # 1.0.0a2: retire the hand-rolled Flutter AgUiClient in favor of
    # the forge_canvas package version (reconnect + Last-Event-ID).
    (
        "apps/*/lib/src/features/chat/data/ag_ui_client.dart",
        "Flutter hand-rolled SSE client (superseded by forge_canvas)",
    ),
]


def run(project_root: Path, dry_run: bool = False, quiet: bool = False) -> MigrationReport:
    report = MigrationReport(name=NAME, applied=False)

    for glob, label in _LEGACY_TARGETS:
        for path in project_root.glob(glob):
            legacy_target = path.with_suffix(path.suffix + ".legacy")
            if legacy_target.exists():
                continue
            if dry_run:
                report.changes.append(f"would rename: {path.relative_to(project_root)} -> .legacy")
            else:
                path.rename(legacy_target)
                report.changes.append(
                    f"renamed: {path.relative_to(project_root)} -> .legacy ({label})"
                )

    report.applied = bool(report.changes) and not dry_run
    if not report.changes:
        report.skipped_reason = "no legacy files found"
    return report
