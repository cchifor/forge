"""Codemod: rewrite deprecated option aliases in ``forge.toml``.

Epic G (1.1.0-alpha.1) — every Option can declare ``aliases=(...,)`` for
paths that previously pointed at it. The resolver rewrites aliases to
canonical paths at every ``forge --update`` and emits a deprecation
warning. This codemod makes the rewrite persistent: it reads
``forge.toml``'s ``[forge.options]`` table, finds any keys that match a
declared alias, writes them back under the canonical path, and removes
the alias entries. Safe to re-run — a second pass is a no-op because
the first pass left only canonical keys.

Why this codemod rather than letting the warning fire forever? Because
``forge --update``'s idempotency argument says generated projects
should converge on a stable shape. Aliased keys in ``forge.toml`` keep
firing the warning on every update; rewriting once moves the project
to steady state.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from forge.migrations.base import MigrationReport
from forge.options import OPTION_ALIAS_INDEX

NAME = "rename-options"
FROM = "1.1.0-alpha.1"
TO = "1.1.0"
DESCRIPTION = "Rewrite deprecated option aliases in forge.toml to canonical paths."


def run(project_root: Path, dry_run: bool, quiet: bool) -> MigrationReport:
    """Rewrite forge.toml's [forge.options] table through the alias index.

    Return a report listing every rewrite performed. A report with an
    empty changes list + applied=False indicates the project had no
    aliased keys to rewrite (the steady state post-rewrite).
    """
    manifest = project_root / "forge.toml"
    if not manifest.is_file():
        return MigrationReport(
            name=NAME,
            applied=False,
            skipped_reason=f"No forge.toml at {project_root}",
        )

    # tomlkit preserves comments + ordering so the rewrite doesn't
    # churn unrelated sections of forge.toml.
    import tomlkit  # noqa: PLC0415

    body = manifest.read_text(encoding="utf-8")
    doc = tomlkit.parse(body)
    forge_section = doc.get("forge") or {}
    options_table = forge_section.get("options") if forge_section else None

    if options_table is None:
        return MigrationReport(
            name=NAME,
            applied=False,
            skipped_reason="forge.toml has no [forge.options] table",
        )

    rewrites: list[tuple[str, str, Any]] = []  # (alias, canonical, value)
    for key in list(options_table.keys()):
        canonical = OPTION_ALIAS_INDEX.get(key)
        if canonical is None:
            continue
        value = options_table[key]
        # Skip when the user already sets the canonical path — the
        # resolver would raise on the conflict, but we should surface
        # this in the codemod output so the user knows their alias is
        # being dropped.
        if canonical in options_table:
            if not quiet:
                print(
                    f"  [rename-options] {key!r} → {canonical!r}: skipping (canonical already set)"
                )
            # Don't drop here either; leaving both gives the resolver
            # a chance to complain loudly so the user picks one.
            continue
        rewrites.append((key, canonical, value))

    if not rewrites:
        return MigrationReport(
            name=NAME,
            applied=False,
            skipped_reason="No aliased option keys found in forge.toml",
        )

    changes: list[str] = []
    if not dry_run:
        for alias, canonical, value in rewrites:
            options_table[canonical] = value
            del options_table[alias]
        manifest.write_text(tomlkit.dumps(doc), encoding="utf-8")

    for alias, canonical, _ in rewrites:
        changes.append(f"rewrote {alias!r} → {canonical!r}")
        if not quiet:
            tag = "[dry-run]" if dry_run else "[apply]"
            print(f"  {tag} rename-options: {alias} → {canonical}")

    return MigrationReport(name=NAME, applied=not dry_run, changes=changes)
