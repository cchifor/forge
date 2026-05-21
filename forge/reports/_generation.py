"""GenerationReport dataclass.

The report captures every observable input + output of a
``forge.generator.generate()`` run so an autonomous agent driving
forge headlessly can:

* re-derive the *effective* option mapping the generator actually saw
  (after defaults + CLI rewrites — see :class:`HiddenMutation`),
* tell which options the *user* set versus which the resolver
  filled in,
* walk the resolved fragment DAG without re-resolving it,
* spot every file forge wrote, with its origin and content hash,
* read the warnings that human callers would otherwise see only on
  stderr (broken plugins, skipped toolchains, codegen blips),
* know what to do next (typically ``cd <project_root> && docker
  compose up``).

The report is populated incrementally during generation. The
generator constructs a fresh :class:`GenerationReport`, threads it
through its private phase helpers, and each helper appends to the
relevant collection. The CLI then serialises the report via
:meth:`to_dict` and merges it into the existing thin ``--json``
payload so back-compat callers continue to see their old keys.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Bumped whenever a backward-incompatible shape change lands. Additive
# field additions don't bump; consumers MUST tolerate unknown keys.
REPORT_VERSION = 1


@dataclass(frozen=True)
class FileInventoryEntry:
    """One file forge wrote during generation.

    ``path`` is the project-relative POSIX path. ``origin`` mirrors
    :class:`forge.sync.provenance.ProvenanceOrigin` (``base-template``
    / ``fragment`` / ``user``). ``sha256`` is the LF-normalised SHA-256
    of the content at emission time. ``fragment_name`` / ``template_name``
    identify the emitter when known (e.g. ``"rag_qdrant"`` for a fragment
    write, ``"services/python-service-template"`` for a base-template
    write).
    """

    path: str
    origin: str
    sha256: str
    fragment_name: str | None = None
    template_name: str | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "path": self.path,
            "origin": self.origin,
            "sha256": self.sha256,
        }
        if self.fragment_name:
            out["fragment_name"] = self.fragment_name
        if self.template_name:
            out["template_name"] = self.template_name
        return out


@dataclass(frozen=True)
class HiddenMutation:
    """A CLI-side rewrite of a user-visible field.

    Surfacing these is the original motivation for this initiative —
    pre-#5, the CLI silently coerced ``auth.mode`` to ``"none"`` when
    Keycloak was disabled (see ``forge/cli/builder.py:271``), and the
    agent driving the run had no way to know the value it asked for
    isn't what generation acted on. ``path`` is dotted-path notation
    matching ``ProjectConfig.options`` keys (or a top-level config key
    like ``include_keycloak``). ``previous`` / ``current`` are the
    pre- and post-coercion values; ``reason`` is a human-readable
    explanation suitable for surfacing in an error envelope.
    """

    path: str
    previous: Any
    current: Any
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "previous": self.previous,
            "current": self.current,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class SkippedToolchain:
    """A backend toolchain pass that was skipped this run.

    The generator skips toolchain ``verify()`` (lint + tests) when
    ``quiet=True`` or ``dry_run=True``. The skipped entry tells the
    agent what *would* have run and why so it can either re-run with
    ``--verbose`` or run the equivalent manual command itself.
    """

    backend: str
    language: str
    phase: str  # "install" / "verify" / "post_generate"
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "backend": self.backend,
            "language": self.language,
            "phase": self.phase,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class NextAction:
    """A suggested follow-up command for the caller.

    ``command`` is a shell-ready string (e.g. ``"docker compose up"``);
    ``description`` is the human-readable why. ``cwd`` is the
    project-relative directory the command should run from (``"."``
    for project root).
    """

    command: str
    description: str
    cwd: str = "."

    def to_dict(self) -> dict[str, Any]:
        return {
            "command": self.command,
            "description": self.description,
            "cwd": self.cwd,
        }


@dataclass
class GenerationReport:
    """Full picture of a single ``forge.generator.generate`` invocation.

    Mutable so the generator can append to the collections as each
    phase reports its outcome. Consumers should treat the dataclass
    as read-only after generation returns; :meth:`to_dict` produces
    a JSON-serialisable snapshot for emission.

    Fields:

    * ``project_root`` — absolute path to the generated project (mirror
      of :func:`forge.generator.generate`'s return value).
    * ``effective_config`` — flat dotted-path dict of the fully-
      defaulted option mapping the resolver produced. Matches
      ``ResolvedPlan.option_values`` keyed by canonical paths.
    * ``option_origins`` — parallel-keyed ``"user"`` / ``"default"``
      dict for ``effective_config``. Mirrors the ``[forge.option_origins]``
      manifest table.
    * ``fragment_graph`` — adjacency list of the resolved fragment
      DAG: ``{fragment_name: [direct dependency names]}``. Order
      reflects the topological apply order; an empty list means
      the fragment has no dependencies.
    * ``file_inventory`` — every file forge wrote, as
      :class:`FileInventoryEntry` records.
    * ``provenance_sidecar_paths`` — project-relative paths of
      forge-owned sidecar / manifest files (``forge.toml``, copier
      answer files). Lets a curious agent locate the manifest
      without guessing.
    * ``warnings`` — human-readable strings the generator emitted to
      stderr or logged at WARN level. Plugin-load failures, codegen
      blips, missing optional dependencies.
    * ``skipped_toolchains`` — backend toolchain passes that were
      not run this invocation (typically because of ``--quiet`` or
      ``--dry-run``). See :class:`SkippedToolchain`.
    * ``next_actions`` — agent-actionable follow-up commands (``docker
      compose up``, ``forge --update``, …). See :class:`NextAction`.
    * ``hidden_mutations`` — CLI-side coercions the caller's input
      went through before generation (``auth.mode`` rewrite when
      Keycloak is disabled, etc.). See :class:`HiddenMutation`.
    * ``rollback_hint`` — short human-readable string describing how
      to undo this generation (e.g. ``"rm -rf <project_root>"``). The
      generator populates a sensible default but the CLI may override
      with a more nuanced suggestion (``git reset --hard`` when the
      project root is a pre-existing git repo).
    """

    project_root: str = ""
    effective_config: dict[str, Any] = field(default_factory=dict)
    option_origins: dict[str, str] = field(default_factory=dict)
    fragment_graph: dict[str, list[str]] = field(default_factory=dict)
    file_inventory: list[FileInventoryEntry] = field(default_factory=list)
    provenance_sidecar_paths: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    skipped_toolchains: list[SkippedToolchain] = field(default_factory=list)
    next_actions: list[NextAction] = field(default_factory=list)
    hidden_mutations: list[HiddenMutation] = field(default_factory=list)
    rollback_hint: str = ""

    # Schema version — bumped on backward-incompatible shape changes.
    _report_version: int = REPORT_VERSION

    def add_warning(self, msg: str) -> None:
        """Append a warning string. Duplicates are silently dropped so
        repeated phase errors don't bloat the report."""
        if msg not in self.warnings:
            self.warnings.append(msg)

    def add_hidden_mutation(self, mutation: HiddenMutation) -> None:
        """Append a hidden-mutation record. Duplicates (same path +
        same previous/current) are dropped."""
        for existing in self.hidden_mutations:
            if (
                existing.path == mutation.path
                and existing.previous == mutation.previous
                and existing.current == mutation.current
            ):
                return
        self.hidden_mutations.append(mutation)

    def add_skipped_toolchain(self, entry: SkippedToolchain) -> None:
        """Append a skipped-toolchain record."""
        self.skipped_toolchains.append(entry)

    def add_next_action(self, action: NextAction) -> None:
        """Append a next-action suggestion. Duplicates (same
        ``command`` + ``cwd``) are dropped."""
        for existing in self.next_actions:
            if existing.command == action.command and existing.cwd == action.cwd:
                return
        self.next_actions.append(action)

    def to_dict(self) -> dict[str, Any]:
        """Serialize the report to a JSON-friendly dict.

        Empty / falsy collections are omitted so the emitted JSON
        stays compact; downstream consumers that pin a schema must
        treat absent fields as "default-valued" rather than missing.
        ``_report_version`` and ``project_root`` are always present;
        other fields are always present in their non-empty form.
        """
        out: dict[str, Any] = {
            "_report_version": self._report_version,
            "project_root": self.project_root,
            "effective_config": dict(self.effective_config),
            "option_origins": dict(self.option_origins),
            "fragment_graph": {
                name: list(deps) for name, deps in self.fragment_graph.items()
            },
            "file_inventory": [entry.to_dict() for entry in self.file_inventory],
            "provenance_sidecar_paths": list(self.provenance_sidecar_paths),
            "warnings": list(self.warnings),
            "skipped_toolchains": [e.to_dict() for e in self.skipped_toolchains],
            "next_actions": [a.to_dict() for a in self.next_actions],
            "hidden_mutations": [m.to_dict() for m in self.hidden_mutations],
        }
        if self.rollback_hint:
            out["rollback_hint"] = self.rollback_hint
        return out
