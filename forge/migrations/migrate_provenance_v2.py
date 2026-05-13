"""Codemod: upgrade v1 ``forge.toml`` manifests to schema v2 in place.

Phase 1.2 (1.2.0-alpha.1) introduces the v2 manifest shape — see
``forge.forge_toml`` for the full grammar. v1 manifests (everything
generated before this PR) carry only a sparse subset of the fields v2
expects:

* ``[forge]`` has no ``schema_version`` key.
* ``[forge.template_versions]`` is absent.
* Per-file entries in ``[forge.provenance."<path>"]`` carry just
  ``{origin, sha256, fragment_name?}`` — ``fragment_version`` was
  declared on the dataclass but never populated by the old code.
* Per-block entries in ``[forge.merge_blocks."<key>"]`` carry just
  ``{sha256}``.
* BEGIN sentinels in injected files are of the form
  ``# FORGE:BEGIN <feature_key>:<MARKER_NAME>`` — no ``fp:<hex8>``
  trailer.

This codemod is a **best-effort enrichment**, not a hard rewrite:

1. Detect a v1 manifest (``schema_version`` absent or ``< 2``); skip
   when already v2 (idempotent).
2. Populate ``fragment_version`` for fragment-origin entries by looking
   up the fragment in the current ``FRAGMENT_REGISTRY`` and recording
   the *forge version at migration time* as the version. Unknown
   fragments (deprecated, third-party, etc.) are logged and left with
   ``fragment_version`` absent — the harvester is designed to tolerate
   that.
3. For each ``[forge.merge_blocks]`` entry, parse the key
   (``{rel_path}::{feature_key}:{marker}``) to derive ``fragment_name``
   — the ``feature_key`` segment IS the fragment name for built-in
   fragments.
4. For each ``[forge.merge_blocks]`` entry, locate the target file on
   disk and re-anchor the BEGIN sentinel with ``fp:<hex8>``. The
   fingerprint is computed from the *in-file* block body, NOT from a
   freshly-rendered fragment snippet — see the trade-off note below.
5. Set ``schema_version = 2``, populate ``[forge.template_versions]``
   from the existing ``[forge.templates]`` keys + current forge
   version, and write back.

Subtle trade-off (step 4): in v2-emitted code, the BEGIN sentinel's
``fp:<hex8>`` is ``sha256(rendered_snippet)[:8]`` — the snippet as the
fragment shipped it, BEFORE the user could edit. For migration we
don't have the rendered snippet without re-running the appliers
(Jinja can fail on missing options, fragments may have been removed,
etc.), so we use the in-file body instead. This is *fingerprint of the
block as it exists on disk now* — a useful harvest recovery anchor,
but NOT byte-identical to what a fresh v2 generation would emit. The
harvester is designed to tolerate fingerprint mismatches; the baseline
``sha256`` (which v1 already records) is the authoritative integrity
check.

The migration explicitly preserves the v1 baseline ``sha256`` — never
recomputed. The user's edits, if any, are reflected in the in-file
body but the manifest record stays anchored to what forge *emitted*
last time. This is the same contract three-way merge relies on.

Acquires the updater lock (``forge.updater_lock``) before mutating so
concurrent ``forge --update --migrate`` runs serialise cleanly.

Re-runnable: a second pass detects ``schema_version >= 2`` and exits
with ``applied=False`` and a clear ``skipped_reason``.
"""

from __future__ import annotations

import logging
from pathlib import Path

import tomlkit

import forge
from forge.fragments import FRAGMENT_REGISTRY
from forge.injectors.sentinels import _block_fingerprint
from forge.migrations.base import MigrationReport
from forge.sync.lock import acquire_lock
from forge.sync.merge import MergeBlockCollector

logger = logging.getLogger(__name__)

NAME = "provenance-v2"
FROM = "1.1.x"
TO = "1.2.0"
DESCRIPTION = (
    "Upgrade pre-1.2 forge.toml manifests to schema v2 — populate "
    "fragment_version, fragment_name, template_versions; add fp:<hex8> "
    "fingerprints to BEGIN sentinels."
)


# Marker prefix used in BEGIN/END sentinels. Imported as a literal here
# (rather than re-importing forge.fragments.MARKER_PREFIX) to keep this
# module dependency-light at migration time — the registry import is
# already heavy enough.
_MARKER_PREFIX = "FORGE:"


def run(project_root: Path, dry_run: bool, quiet: bool) -> MigrationReport:
    """Upgrade a v1 ``forge.toml`` to v2 in place — best-effort enrichment.

    See module docstring for the full algorithm. Returns a
    :class:`MigrationReport` whose ``changes`` list summarises every
    enrichment performed (one entry per file touched / per fragment
    resolved / per sentinel fingerprinted).
    """
    manifest = project_root / "forge.toml"
    if not manifest.is_file():
        return MigrationReport(
            name=NAME,
            applied=False,
            skipped_reason=f"No forge.toml at {project_root}",
        )

    body = manifest.read_text(encoding="utf-8")
    doc = tomlkit.parse(body)
    forge_section = doc.get("forge")
    if forge_section is None:
        return MigrationReport(
            name=NAME,
            applied=False,
            skipped_reason=f"{manifest}: missing [forge] section",
        )

    # Idempotency guard — already v2, nothing to do.
    raw_schema = forge_section.get("schema_version")
    current_schema = int(raw_schema) if isinstance(raw_schema, int) else 1
    if current_schema >= 2:
        return MigrationReport(
            name=NAME,
            applied=False,
            skipped_reason=f"forge.toml is already schema v{current_schema}",
        )

    # Collect every change before touching disk so dry-run is honest
    # and so the lock window stays as narrow as possible.
    changes: list[str] = []
    files_touched: set[str] = set()
    sentinels_fingerprinted = 0
    fragment_versions_resolved = 0
    fragment_versions_unresolved: set[str] = set()
    errors: list[str] = []

    # --- 1. Stamp schema_version --------------------------------------------
    changes.append("set schema_version = 2")

    # --- 2. Populate template_versions if missing ---------------------------
    if "template_versions" not in forge_section:
        templates = forge_section.get("templates") or {}
        if templates:
            # We don't actually know per-template versions historically
            # (v1 didn't record them). Best we can do at migration time:
            # stamp the current forge version against each template
            # key. v2-generated manifests will overwrite with the real
            # per-template versions on the next ``forge --update``.
            tv_changes = sorted(str(k) for k in templates)
            for key in tv_changes:
                changes.append(f"stamped template_versions.{key} = {forge.__version__!r}")
        else:
            changes.append("added empty [forge.template_versions]")

    # --- 3. Enrich [forge.provenance] entries -------------------------------
    provenance_table = forge_section.get("provenance") or {}
    for rel_path, entry in dict(provenance_table).items():
        if not isinstance(entry, dict):
            continue
        origin = entry.get("origin")
        if origin != "fragment":
            continue
        if entry.get("fragment_version"):
            continue  # already populated — leave it alone
        fragment_name = entry.get("fragment_name")
        if not fragment_name:
            continue
        if fragment_name in FRAGMENT_REGISTRY:
            fragment_versions_resolved += 1
            changes.append(
                f"resolved fragment_version for {rel_path!s} "
                f"({fragment_name} → {forge.__version__})"
            )
        else:
            fragment_versions_unresolved.add(str(fragment_name))
            logger.warning(
                "migrate-provenance-v2: fragment %r referenced by %s is not in "
                "the current FRAGMENT_REGISTRY — leaving fragment_version "
                "absent. (Plugin uninstalled? Fragment renamed upstream?)",
                fragment_name,
                rel_path,
            )

    # --- 4. Enrich [forge.merge_blocks] entries + sentinel fingerprints -----
    merge_blocks_table = forge_section.get("merge_blocks") or {}
    sentinel_rewrites: list[_SentinelRewrite] = []
    for key, entry in dict(merge_blocks_table).items():
        if not isinstance(entry, dict):
            continue
        parsed = MergeBlockCollector.parse_key(str(key))
        if parsed is None:
            errors.append(f"unparseable merge_blocks key: {key!r}")
            continue
        rel_path, feature_key, marker = parsed
        target = project_root / rel_path

        # Always derive fragment_name from the key — it's the canonical
        # source. Fragment_version follows the same rule as provenance
        # entries (resolved iff in current registry).
        wants_name = not entry.get("fragment_name")
        wants_version = not entry.get("fragment_version")
        in_registry = feature_key in FRAGMENT_REGISTRY

        if wants_name:
            changes.append(f"derived fragment_name for {key!s} → {feature_key}")
        if wants_version and in_registry:
            fragment_versions_resolved += 1
            changes.append(
                f"resolved fragment_version for {key!s} ({feature_key} → {forge.__version__})"
            )
        elif wants_version and not in_registry:
            fragment_versions_unresolved.add(feature_key)
            logger.warning(
                "migrate-provenance-v2: merge_block fragment %r (in %s) is not "
                "in the current FRAGMENT_REGISTRY — leaving fragment_version "
                "absent.",
                feature_key,
                rel_path,
            )

        # Sentinel re-anchoring: locate the BEGIN line and append the
        # fingerprint. Skip silently when the target file is gone (the
        # block has been deleted by the user) or when the BEGIN line
        # already carries a fingerprint.
        if not target.is_file():
            errors.append(
                f"merge_block target missing on disk: {rel_path!s} "
                f"(skipping sentinel fingerprint for {key!s})"
            )
            continue
        rewrite = _plan_sentinel_rewrite(target, feature_key, marker)
        if rewrite is not None:
            sentinel_rewrites.append(rewrite)
            files_touched.add(rel_path)
            sentinels_fingerprinted += 1
            changes.append(
                f"will add fp:{rewrite.fingerprint} to BEGIN sentinel "
                f"in {rel_path!s} ({feature_key}:{rewrite.naked_marker})"
            )

    if dry_run:
        return _build_report(
            applied=False,
            changes=changes,
            files_touched=files_touched,
            sentinels_fingerprinted=sentinels_fingerprinted,
            fragment_versions_resolved=fragment_versions_resolved,
            fragment_versions_unresolved=fragment_versions_unresolved,
            errors=errors,
            quiet=quiet,
        )

    # --- 5. Write phase — under the updater lock ---------------------------
    with acquire_lock(project_root):
        # 5a. Sentinel rewrites in target files.
        for rewrite in sentinel_rewrites:
            rewrite.apply()

        # 5b. forge.toml rewrites — re-read tomlkit so we apply mutations
        #     on the canonical doc and keep comment/ordering preservation.
        forge_section["schema_version"] = 2

        if "template_versions" not in forge_section:
            tv_tbl = tomlkit.table()
            templates = forge_section.get("templates") or {}
            for tname in sorted(str(k) for k in templates):
                tv_tbl.add(tname, forge.__version__)
            forge_section["template_versions"] = tv_tbl

        # Re-walk provenance, this time mutating.
        provenance_table_w = forge_section.get("provenance") or {}
        for _rel_path, entry in dict(provenance_table_w).items():
            if not isinstance(entry, dict):
                continue
            if entry.get("origin") != "fragment":
                continue
            if entry.get("fragment_version"):
                continue
            fragment_name = entry.get("fragment_name")
            if not fragment_name or fragment_name not in FRAGMENT_REGISTRY:
                continue
            entry["fragment_version"] = forge.__version__

        # Re-walk merge_blocks.
        merge_blocks_table_w = forge_section.get("merge_blocks") or {}
        for key, entry in dict(merge_blocks_table_w).items():
            if not isinstance(entry, dict):
                continue
            parsed = MergeBlockCollector.parse_key(str(key))
            if parsed is None:
                continue
            _, feature_key, _ = parsed
            if not entry.get("fragment_name"):
                entry["fragment_name"] = feature_key
            if not entry.get("fragment_version") and feature_key in FRAGMENT_REGISTRY:
                entry["fragment_version"] = forge.__version__

        manifest.write_text(tomlkit.dumps(doc), encoding="utf-8")

    return _build_report(
        applied=True,
        changes=changes,
        files_touched=files_touched,
        sentinels_fingerprinted=sentinels_fingerprinted,
        fragment_versions_resolved=fragment_versions_resolved,
        fragment_versions_unresolved=fragment_versions_unresolved,
        errors=errors,
        quiet=quiet,
    )


def _build_report(
    *,
    applied: bool,
    changes: list[str],
    files_touched: set[str],
    sentinels_fingerprinted: int,
    fragment_versions_resolved: int,
    fragment_versions_unresolved: set[str],
    errors: list[str],
    quiet: bool,
) -> MigrationReport:
    """Assemble the :class:`MigrationReport` + emit progress output.

    Counters are folded into the ``changes`` list as a summary header so
    callers reading the report don't have to scan every line — but the
    per-change rows are kept so they remain auditable.
    """
    summary_lines = [
        f"files_touched: {len(files_touched)}",
        f"sentinels_fingerprinted: {sentinels_fingerprinted}",
        f"fragment_versions_resolved: {fragment_versions_resolved}",
        f"fragment_versions_unresolved: {len(fragment_versions_unresolved)}"
        + (f" ({sorted(fragment_versions_unresolved)})" if fragment_versions_unresolved else ""),
        f"errors: {len(errors)}",
    ]
    full_changes = ["summary: " + "; ".join(summary_lines), *changes]
    if errors:
        full_changes.extend(f"error: {e}" for e in errors)

    if not quiet:
        tag = "[apply]" if applied else "[dry-run]"
        print(f"  {tag} {NAME}: {summary_lines[0]}, {summary_lines[1]}")
        if fragment_versions_unresolved:
            print(
                f"  {tag} {NAME}: WARN unresolved fragments → "
                f"{sorted(fragment_versions_unresolved)}"
            )

    return MigrationReport(name=NAME, applied=applied, changes=full_changes)


class _SentinelRewrite:
    """One pending BEGIN-sentinel rewrite — captured at plan time, applied later.

    The fingerprint is computed from the *in-file* block body at plan
    time, then the BEGIN line is rewritten in place when ``apply()``
    fires. We don't re-read the body inside ``apply()`` because dry-run
    needs the fingerprint in its report.
    """

    __slots__ = ("file", "begin_line_idx", "rewritten_line", "fingerprint", "naked_marker")

    def __init__(
        self,
        *,
        file: Path,
        begin_line_idx: int,
        rewritten_line: str,
        fingerprint: str,
        naked_marker: str,
    ) -> None:
        self.file = file
        self.begin_line_idx = begin_line_idx
        self.rewritten_line = rewritten_line
        self.fingerprint = fingerprint
        self.naked_marker = naked_marker

    def apply(self) -> None:
        """Rewrite the BEGIN sentinel line in place."""
        # Re-read the file under the lock to honour any concurrent
        # in-flight changes the planner didn't see.
        text = self.file.read_text(encoding="utf-8")
        lines = text.splitlines(keepends=True)
        # Defensive: if the file has been mutated since we planned, drop
        # silently rather than corrupting an out-of-position line.
        if self.begin_line_idx >= len(lines):
            return
        if "BEGIN" not in lines[self.begin_line_idx]:
            return
        lines[self.begin_line_idx] = self.rewritten_line
        self.file.write_text("".join(lines), encoding="utf-8")


def _plan_sentinel_rewrite(
    file: Path,
    feature_key: str,
    marker: str,
) -> _SentinelRewrite | None:
    """Plan (don't apply) a BEGIN-sentinel fingerprint rewrite for one block.

    Returns ``None`` when the BEGIN line is missing, already carries a
    fingerprint (``fp:<hex8>``), or the END is missing/out-of-order.
    The planner reads the file to compute the fingerprint over the
    current in-file body — see the module docstring for the trade-off
    discussion.
    """
    naked = marker[len(_MARKER_PREFIX) :] if marker.startswith(_MARKER_PREFIX) else marker
    tag = f"{feature_key}:{naked}"
    begin_needle = f"{_MARKER_PREFIX}BEGIN {tag}"
    end_needle = f"{_MARKER_PREFIX}END {tag}"

    try:
        text = file.read_text(encoding="utf-8")
    except OSError:
        return None

    lines = text.splitlines(keepends=True)
    begin_idx = next((i for i, line in enumerate(lines) if begin_needle in line), None)
    end_idx = next((i for i, line in enumerate(lines) if end_needle in line), None)
    if begin_idx is None or end_idx is None or end_idx <= begin_idx:
        return None

    begin_line = lines[begin_idx]
    # Already fingerprinted? Idempotent skip — look for `fp:` followed by
    # hex on the BEGIN line.
    if " fp:" in begin_line:
        return None

    # Compute fingerprint over the in-file body (lines strictly between
    # BEGIN and END). This is the recovery-anchor variant — see module
    # docstring. The newline-keep ``splitlines(keepends=True)`` means
    # we already have line endings; the rendered_snippet form (without
    # the trailing newline on the last line) would differ from what a
    # fresh emit produces by one byte, but the 8-hex anchor is robust
    # enough that harvest still finds the block.
    body = "".join(lines[begin_idx + 1 : end_idx])
    fingerprint = _block_fingerprint(body.rstrip("\n"))

    # Build the rewritten BEGIN line. Preserve everything up to the
    # trailing newline + add ` fp:<hex8>` before the newline.
    stripped = begin_line.rstrip("\r\n")
    line_ending = begin_line[len(stripped) :] or "\n"
    rewritten_line = f"{stripped} fp:{fingerprint}{line_ending}"

    return _SentinelRewrite(
        file=file,
        begin_line_idx=begin_idx,
        rewritten_line=rewritten_line,
        fingerprint=fingerprint,
        naked_marker=naked,
    )
