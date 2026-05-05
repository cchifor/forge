"""Codemod: promote Phase-A flat option paths to Phase-B2 canonical shape.

Phase C completion — sibling to ``migrate_rename_options.py``. The
existing codemod handles ``forge.toml``'s ``[forge.options]`` table via
``OPTION_ALIAS_INDEX``. This codemod adds YAML + JSON config coverage
(the files users pass via ``forge --config``) so a Phase-B2 rename
propagates to every config surface in one pass.

The alias rewrite is the same as ``migrate_rename_options`` uses — the
registered ``aliases=(...)`` tuple on each Option drives the mapping.
What's new is:

* discovery: walk the project root for ``*.yaml`` / ``*.yml`` /
  ``*.json`` files whose top-level ``options`` block (or ``[forge]
  options`` for TOML) contains an aliased key;
* rewrite in place while preserving comments where the file format
  supports it (YAML via ruamel.yaml if available, else stdlib; TOML via
  tomlkit).

Safe to re-run — a second pass finds no aliased keys and exits with
``applied=False``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from forge.migrations.base import MigrationReport
from forge.options import OPTION_ALIAS_INDEX

NAME = "layer-modes"
FROM = "1.1.0"
TO = "1.2.0"
DESCRIPTION = (
    "Promote Phase-A flat layer-mode paths (e.g. frontend.api_target_url) "
    "to the canonical B2 shape (frontend.api_target.url) across "
    "forge.toml and YAML/JSON config files."
)

# Files likely to hold forge config. Relative to project_root.
_CONFIG_GLOBS = ("*.yaml", "*.yml", "*.json")


def run(project_root: Path, dry_run: bool, quiet: bool) -> MigrationReport:
    """Walk ``project_root`` for forge config files and promote aliases."""
    if not project_root.is_dir():
        return MigrationReport(
            name=NAME,
            applied=False,
            skipped_reason=f"Project root does not exist: {project_root}",
        )

    changes: list[str] = []
    any_applied = False

    # 1. forge.toml — tomlkit preserves comments + ordering.
    toml_path = project_root / "forge.toml"
    if toml_path.is_file():
        rewrote, _note = _rewrite_toml(toml_path, dry_run, quiet)
        if rewrote:
            any_applied = any_applied or not dry_run
            changes.extend(rewrote)

    # 2. YAML / JSON config files (user-supplied ``--config`` inputs).
    for pattern in _CONFIG_GLOBS:
        for path in project_root.glob(pattern):
            if path.name == "forge.toml":
                continue  # already handled above
            rewrote, _note = _rewrite_yaml_or_json(path, dry_run, quiet)
            if rewrote:
                any_applied = any_applied or not dry_run
                changes.extend(rewrote)

    if not changes:
        return MigrationReport(
            name=NAME,
            applied=False,
            skipped_reason="No aliased layer-mode keys found in project configs",
        )

    return MigrationReport(name=NAME, applied=any_applied, changes=changes)


# -- TOML path ---------------------------------------------------------------


def _rewrite_toml(path: Path, dry_run: bool, quiet: bool) -> tuple[list[str], str | None]:
    """Rewrite aliased keys in forge.toml. Mirrors ``migrate_rename_options``
    but scoped to layer-mode aliases — independent invocation."""
    import tomlkit  # noqa: PLC0415

    body = path.read_text(encoding="utf-8")
    doc = tomlkit.parse(body)
    forge_section = doc.get("forge") or {}
    options_table = forge_section.get("options") if forge_section else None
    if options_table is None:
        return [], "no [forge.options] table"

    rewrites = _collect_rewrites(dict(options_table))
    if not rewrites:
        return [], "no aliased keys"

    changes: list[str] = []
    for alias, canonical, value in rewrites:
        if canonical in options_table:
            if not quiet:
                print(
                    f"  [layer-modes] {path.name}: skip {alias!r} -> "
                    f"{canonical!r} (canonical already set)"
                )
            continue
        if not dry_run:
            options_table[canonical] = value
            del options_table[alias]
        tag = "[dry-run]" if dry_run else "[apply]"
        changes.append(f"{path.name}: {alias!r} -> {canonical!r}")
        if not quiet:
            print(f"  {tag} layer-modes: {path.name}: {alias} -> {canonical}")

    if changes and not dry_run:
        path.write_text(tomlkit.dumps(doc), encoding="utf-8")
    return changes, None


# -- YAML / JSON path --------------------------------------------------------


def _rewrite_yaml_or_json(path: Path, dry_run: bool, quiet: bool) -> tuple[list[str], str | None]:
    """Rewrite aliased keys in a YAML or JSON config file.

    Looks for an ``options`` top-level mapping (the convention forge's
    own ``--config`` loader uses). Unknown file shapes (no ``options``
    key, or flat non-dict top-level) are silently skipped — this
    codemod is opt-in via file content, not file name.
    """
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return [], "unreadable"

    data = _load_yaml_or_json(raw, path.suffix.lower())
    if not isinstance(data, dict):
        return [], "top-level not a mapping"

    options = data.get("options")
    if not isinstance(options, dict):
        return [], "no options mapping"

    rewrites = _collect_rewrites(options)
    if not rewrites:
        return [], "no aliased keys"

    changes: list[str] = []
    for alias, canonical, value in rewrites:
        if canonical in options:
            if not quiet:
                print(
                    f"  [layer-modes] {path.name}: skip {alias!r} -> "
                    f"{canonical!r} (canonical already set)"
                )
            continue
        if not dry_run:
            options[canonical] = value
            del options[alias]
        tag = "[dry-run]" if dry_run else "[apply]"
        changes.append(f"{path.name}: {alias!r} -> {canonical!r}")
        if not quiet:
            print(f"  {tag} layer-modes: {path.name}: {alias} -> {canonical}")

    if changes and not dry_run:
        _dump_yaml_or_json(data, path)
    return changes, None


def _load_yaml_or_json(raw: str, suffix: str) -> Any:
    if suffix == ".json":
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None
    try:
        from ruamel.yaml import YAML  # noqa: PLC0415  # ty: ignore[unresolved-import]

        yaml = YAML(typ="rt")
        return yaml.load(raw)
    except ImportError:
        try:
            import yaml as pyyaml  # noqa: PLC0415

            return pyyaml.safe_load(raw)
        except ImportError:
            return None
    except Exception:  # noqa: BLE001
        return None


def _dump_yaml_or_json(data: Any, path: Path) -> None:
    suffix = path.suffix.lower()
    if suffix == ".json":
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        return
    try:
        from ruamel.yaml import YAML  # noqa: PLC0415  # ty: ignore[unresolved-import]

        yaml = YAML(typ="rt")
        with path.open("w", encoding="utf-8") as fh:
            yaml.dump(data, fh)
    except ImportError:
        import yaml as pyyaml  # noqa: PLC0415

        with path.open("w", encoding="utf-8") as fh:
            pyyaml.safe_dump(data, fh, sort_keys=False)


# -- Shared ------------------------------------------------------------------


def _collect_rewrites(
    options: dict[str, Any],
) -> list[tuple[str, str, Any]]:
    """Walk an options mapping and return ``[(alias, canonical, value)]``
    for every alias that needs rewriting.
    """
    rewrites: list[tuple[str, str, Any]] = []
    for key in list(options):
        canonical = OPTION_ALIAS_INDEX.get(key)
        if canonical is None:
            continue
        rewrites.append((key, canonical, options[key]))
    return rewrites
