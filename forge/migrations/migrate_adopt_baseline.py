"""Codemod: adopt current file SHAs as the manifest baseline.

P0.1 (1.1.0-alpha.2) — file-level three-way merge needs a baseline SHA
for every fragment-authored file before it can detect drift on
``forge --update``. Pre-1.1 projects have empty (or partial)
``[forge.provenance]`` tables; under merge mode every pre-existing file
falls into the ``no-baseline`` row of the decision table and is
preserved as user-authored — safe but inert.

This migration is the "I trust my current tree" escape hatch: it walks
the project's source roots, hashes every file, and stamps the SHAs into
``[forge.provenance]`` so future ``--update`` runs have something to
three-way-decide against. Strictly opt-in (run via ``forge --migrate``
or ``forge --migrate-only adopt-baseline``); never auto-applied.

Files are stamped with ``origin="base-template"`` because the codemod
can't distinguish fragment-authored from user-authored content after
the fact. The merge logic treats both base-template and fragment
records as baselines, so the practical effect is the same: future
fragment changes can be detected and merged. User-added files outside
the source roots are skipped.

Idempotent: a second pass is a no-op because the first pass left every
walked path with a non-empty SHA, and the migration only stamps files
that lack a record.
"""

from __future__ import annotations

from pathlib import Path

from forge.migrations.base import MigrationReport

NAME = "adopt-baseline"
FROM = "1.0.x"
TO = "1.1.0-alpha.2"
DESCRIPTION = (
    "Stamp current file SHAs into forge.toml's [forge.provenance] so "
    "merge mode has baselines to compare against on the next --update."
)

# Roots forge cares about. Files outside these are user territory and
# stay invisible to the merge logic. The list mirrors generator.py's
# TEMPLATE_DIRS keys so adding a new top-level (e.g. ``packages/``)
# means updating both.
_SOURCE_ROOTS: tuple[str, ...] = ("services", "apps", "tests")

# Subtrees we never walk: large, machine-managed, never fragment-owned.
_SKIP_DIR_NAMES: frozenset[str] = frozenset(
    {
        ".venv",
        ".git",
        "__pycache__",
        "node_modules",
        ".pytest_cache",
        ".ruff_cache",
        ".mypy_cache",
        ".hypothesis",
        "build",
        "dist",
        "target",  # Rust build output
        ".forge",  # forge-internal state
    }
)


def run(project_root: Path, dry_run: bool, quiet: bool) -> MigrationReport:
    """Walk source roots, stamp file SHAs into ``[forge.provenance]``."""
    manifest = project_root / "forge.toml"
    if not manifest.is_file():
        return MigrationReport(
            name=NAME,
            applied=False,
            skipped_reason=f"No forge.toml at {project_root}",
        )

    import tomlkit  # noqa: PLC0415

    from forge.merge import sha256_of_file  # noqa: PLC0415

    body = manifest.read_text(encoding="utf-8")
    doc = tomlkit.parse(body)
    forge_section = doc.get("forge") or {}
    if "provenance" in forge_section:
        provenance_table = forge_section["provenance"]
    else:
        # Create the table if missing — pre-1.1 projects often have no
        # provenance section at all.
        provenance_table = tomlkit.table()
        forge_section["provenance"] = provenance_table

    stamped: list[str] = []
    for root_name in _SOURCE_ROOTS:
        root = project_root / root_name
        if not root.is_dir():
            continue
        for path in _walk_files(root):
            rel = path.relative_to(project_root).as_posix()
            existing = provenance_table.get(rel)
            if existing is not None:
                # Don't clobber prior records — preserves origin labels
                # the previous generation already wrote.
                continue
            sha = sha256_of_file(path)
            entry = tomlkit.inline_table()
            entry["origin"] = "base-template"
            entry["sha256"] = sha
            provenance_table[rel] = entry
            stamped.append(rel)

    if not stamped:
        return MigrationReport(
            name=NAME,
            applied=False,
            skipped_reason="Every file under source roots already has a provenance record.",
        )

    if not dry_run:
        manifest.write_text(tomlkit.dumps(doc), encoding="utf-8")

    if not quiet:
        tag = "[dry-run]" if dry_run else "[apply]"
        print(f"  {tag} adopt-baseline: stamped {len(stamped)} file(s)")
        for rel in stamped[:5]:
            print(f"    + {rel}")
        if len(stamped) > 5:
            print(f"    ... and {len(stamped) - 5} more")

    return MigrationReport(
        name=NAME,
        applied=not dry_run,
        changes=[f"stamped {rel}" for rel in stamped],
    )


def _walk_files(root: Path):
    """Yield every regular file under ``root`` skipping the configured dirs."""
    for entry in root.iterdir():
        if entry.is_dir():
            if entry.name in _SKIP_DIR_NAMES:
                continue
            yield from _walk_files(entry)
        elif entry.is_file():
            # Skip the sidecars themselves — they're transient state.
            if entry.name.endswith(".forge-merge") or entry.name.endswith(".forge-merge.bin"):
                continue
            yield entry
