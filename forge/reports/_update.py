"""UpdateReport dataclass.

Mirrors :class:`forge.reports.GenerationReport` but for
``forge --update`` runs. Adds per-file dispositions describing what
the updater did with each tracked file: kept as-is, in-place rewrite,
three-way merged, conflict (manual review), or sidecar emitted.

The CLI ``--update --json`` path can drop the pre-existing thin
summary dict and emit the report payload directly; the existing keys
(``fragments_applied``, ``forge_version_before`` / ``_after``, etc.)
are still surfaced for back-compat — they live in
``UpdateReport.legacy_summary``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from forge.reports._generation import (
    REPORT_VERSION,
    HiddenMutation,
    NextAction,
    SkippedToolchain,
)

# Per-file disposition. Mirrors the updater's internal vocabulary so
# ``UpdateReport`` consumers don't need to learn a new taxonomy.
FileDisposition = Literal[
    "unchanged",
    "modified",
    "merged",
    "conflict",
    "sidecar-emitted",
    "user-modified-skipped",
]


@dataclass(frozen=True)
class UpdateFileEntry:
    """One file the updater touched (or considered touching).

    ``path`` is project-relative POSIX. ``disposition`` describes the
    final state — see :data:`FileDisposition`. ``sidecar_path`` is
    populated only when ``disposition == "sidecar-emitted"``;
    otherwise ``None``. ``fragment_name`` identifies the fragment that
    re-asserted ownership of the file in this update pass when known.
    """

    path: str
    disposition: FileDisposition
    fragment_name: str | None = None
    sidecar_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "path": self.path,
            "disposition": self.disposition,
        }
        if self.fragment_name:
            out["fragment_name"] = self.fragment_name
        if self.sidecar_path:
            out["sidecar_path"] = self.sidecar_path
        return out


@dataclass
class UpdateReport:
    """Agent-grade summary of a ``forge --update`` invocation.

    Most fields mirror :class:`forge.reports.GenerationReport`
    (effective config, option origins, fragment graph) since an update
    is conceptually a re-resolve + re-apply on top of the recorded
    forge.toml. ``file_dispositions`` is the per-file picture of what
    the updater did. ``legacy_summary`` carries the pre-#5 thin
    dict shape (``fragments_applied``, ``backends``,
    ``forge_version_before`` / ``_after``, ``file_conflicts``,
    ``template_updates``, …) for back-compat — callers that pin the
    old key names keep working.
    """

    project_root: str = ""
    effective_config: dict[str, Any] = field(default_factory=dict)
    option_origins: dict[str, str] = field(default_factory=dict)
    fragment_graph: dict[str, list[str]] = field(default_factory=dict)
    file_dispositions: list[UpdateFileEntry] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    skipped_toolchains: list[SkippedToolchain] = field(default_factory=list)
    next_actions: list[NextAction] = field(default_factory=list)
    hidden_mutations: list[HiddenMutation] = field(default_factory=list)
    legacy_summary: dict[str, Any] = field(default_factory=dict)
    update_mode: str = ""
    rollback_hint: str = ""

    _report_version: int = REPORT_VERSION

    def add_file(self, entry: UpdateFileEntry) -> None:
        self.file_dispositions.append(entry)

    def add_warning(self, msg: str) -> None:
        if msg not in self.warnings:
            self.warnings.append(msg)

    def add_next_action(self, action: NextAction) -> None:
        for existing in self.next_actions:
            if existing.command == action.command and existing.cwd == action.cwd:
                return
        self.next_actions.append(action)

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a JSON-friendly dict.

        Empty collections are emitted as empty lists / dicts (not
        omitted) so consumers can rely on the schema being stable
        across invocations; the only optional fields are
        ``rollback_hint`` and ``update_mode``.
        """
        out: dict[str, Any] = {
            "_report_version": self._report_version,
            "project_root": self.project_root,
            "effective_config": dict(self.effective_config),
            "option_origins": dict(self.option_origins),
            "fragment_graph": {
                name: list(deps) for name, deps in self.fragment_graph.items()
            },
            "file_dispositions": [e.to_dict() for e in self.file_dispositions],
            "warnings": list(self.warnings),
            "skipped_toolchains": [e.to_dict() for e in self.skipped_toolchains],
            "next_actions": [a.to_dict() for a in self.next_actions],
            "hidden_mutations": [m.to_dict() for m in self.hidden_mutations],
            "legacy_summary": dict(self.legacy_summary),
        }
        if self.update_mode:
            out["update_mode"] = self.update_mode
        if self.rollback_hint:
            out["rollback_hint"] = self.rollback_hint
        return out
